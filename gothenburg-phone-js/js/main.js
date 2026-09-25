// Entry point: load the payload, draw the map, wire the panel.
// Pipeline stages 20, 21, 28, 29, 31 build it; stage 30 packs it.
//
// There is no clock: the data has no time of day. The only animation is the
// optional particle layer (direction of travel) and the speed-filter sweep.
import { S } from "./state.js";
import * as phone from "./phone.js";
import { initMap, render } from "./map.js";
import { initUI, update, tickSweep } from "./ui.js";

const loading = document.getElementById("loading");

async function start(){
  if(location.protocol === "file:"){
    loading.innerHTML = "BROWSERS BLOCK DATA FILES OPENED FROM DISK.<br>"+
      "IN THE gothenburg-phone-js FOLDER RUN: node serve.js";
    return;
  }
  if(typeof DecompressionStream === "undefined"){
    loading.innerHTML = "THIS BROWSER CANNOT UNPACK THE DATA.<br>USE A CURRENT CHROME, EDGE, FIREFOX OR SAFARI.";
    return;
  }

  let SW;
  try {
    const r = await fetch("data/sweep.json");
    if(!r.ok) throw new Error("HTTP " + r.status);
    SW = await r.json();
  } catch(err) {
    loading.innerHTML = `COULD NOT LOAD THE DATA (${err.message}).<br>RUN pipeline/30_export_phone_sweep.py`;
    return;
  }
  // CARTO basemap key (config.json next to index.html; optional - without it
  // the tiles show an "API KEY REQUIRED" watermark)
  try {
    const r = await fetch("config.json");
    if(r.ok) S.cartoKey = ((await r.json()).cartoApiKey || "").trim();
  } catch(_) { /* no config: tiles without a key */ }

  // a view can be shared as a link:  #mode=lane&th=8&layers=flows,counts
  const h = new URLSearchParams((location.hash || "").slice(1));
  if(h.has("mode") && phone.MODES.some(m => m.key === h.get("mode"))) S.mode = h.get("mode");
  if(h.has("th")) S.th = Math.max(0, Math.min(8, Number(h.get("th")) || 0));
  if(h.has("layers")){
    const on = new Set(h.get("layers").split(","));
    for(const k of Object.keys(S.layers)) S.layers[k] = on.has(k);
  }

  await phone.load(SW);
  initMap();
  initUI();
  update();
  phone.stateChanged();
  loading.remove();

  // particles drift and the sweep steps; nothing here is a clock
  let prev = performance.now();
  function frame(now){
    const dt = Math.min(0.1, (now-prev)/1000); prev = now;
    phone.tick(dt);
    if(tickSweep(dt) || phone.stateChanged()) update();
    else if(S.layers.particles) render();
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

start();
