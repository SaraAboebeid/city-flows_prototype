// Serve this dashboard locally and open it in the browser.
//
//     node serve.js          // picks a free port from 8775 upwards
//     node serve.js 9000     // or ask for a specific one
//
// Why not a one-liner static server: on machines running Docker or WSL another
// service can hold the same port on IPv6, and browsers resolve "localhost" to
// IPv6 first - so http://localhost:PORT can silently open the wrong app. This
// binds 127.0.0.1 and checks the port is free on IPv4 and IPv6 before using it.
import http from "node:http";
import net from "node:net";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
  ".ico": "image/x-icon", ".woff2": "font/woff2", ".map": "application/json",
};

function freeOn(port, host) {
  return new Promise(resolve => {
    const s = net.createServer();
    s.once("error", () => resolve(false));
    s.listen(port, host, () => s.close(() => resolve(true)));
  });
}
async function freeEverywhere(port) {
  for (const host of ["127.0.0.1", "::1", "::"]) {
    if (!await freeOn(port, host)) return false;
  }
  return true;
}

const server = http.createServer((req, res) => {
  let rel = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (rel.endsWith("/")) rel += "index.html";
  const file = path.join(HERE, path.normalize(rel).replace(/^([/\\])+/, ""));
  if (!file.startsWith(HERE)) {                   // no climbing out of the folder
    res.writeHead(403).end("forbidden");
    return;
  }
  fs.readFile(file, (err, body) => {
    if (err) {
      res.writeHead(404, {"Content-Type": "text/plain"}).end("not found: " + rel);
      return;
    }
    res.writeHead(200, {
      "Content-Type": TYPES[path.extname(file).toLowerCase()] || "application/octet-stream",
      "Cache-Control": "no-cache",                // an edited module is never served stale
    });
    res.end(body);
  });
});

const want = Number(process.argv[2]) || null;
let port = want && await freeEverywhere(want) ? want : null;
if (!port) {
  for (let p = 8775; p < 8900 && !port; p++) if (await freeEverywhere(p)) port = p;
  if (want) console.log(`port ${want} is taken (possibly on IPv6); using ${port} instead`);
}

server.listen(port, "127.0.0.1", () => {
  const url = `http://127.0.0.1:${port}/`;
  console.log(`Göteborg phone flows (FlowSense): ${url}   (Ctrl+C to stop)`);
  const open = process.platform === "win32" ? ["cmd", ["/c", "start", "", url]]
             : process.platform === "darwin" ? ["open", [url]] : ["xdg-open", [url]];
  setTimeout(() => { try { spawn(open[0], open[1], {detached: true, stdio: "ignore"}).unref(); } catch {} }, 600);
});
process.on("SIGINT", () => { console.log("\nstopped"); process.exit(0); });
