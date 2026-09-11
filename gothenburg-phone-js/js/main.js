// Entry point: load the data files, set up state, start the clock.
// Same look as the synthetic-population dashboard (gothenburg-day-js), but
// on FlowSense phone data.
import { S } from "./state.js";
import * as phone from "./phone.js";
import { initMap, render } from "./map.js";
import { initUI, update, paint } from "./ui.js";

const loading = document.getElementById("loading");

async function getJSON(name){
  const r = await fetch("data/" + name);
  if(!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
  return r.json();
}

async function start(){
  if(location.protocol === "file:"){
    loading.innerHTML = "BROWSERS BLOCK DATA FILES OPENED FROM DISK.<br>"+
      "IN THE gothenburg-phone-js FOLDER RUN: python serve.py";
    return;
  }
  if(typeof DecompressionStream === "undefined"){
    loading.innerHTML = "THIS BROWSER CANNOT UNPACK THE DATA.<br>USE A CURRENT CHROME, EDGE, FIREFOX OR SAFARI.";
    return;
  }

  let PH, PV, TP;
  try {
    [PH, PV, TP] = await Promise.all([getJSON("phone.json"), getJSON("phone_views.json"), getJSON("time_profiles.json")]);
  } catch(err) {
    loading.innerHTML = `COULD NOT LOAD THE DATA (${err.message}).<br>RUN pipeline/25_export_phone_dashboard.py`;
    return;
  }
  // CARTO basemap key (config.json next to index.html; optional - without it
  // the tiles show an "API KEY REQUIRED" watermark)
  try {
    const r = await fetch("config.json");
    if(r.ok) S.cartoKey = ((await r.json()).cartoApiKey || "").trim();
  } catch(_) { /* no config: tiles without a key */ }

  await phone.load(PH, PV, TP);
  initMap();
  initUI();
  update();
  phone.timeChanged();
  loading.remove();

  // ---------- clock ----------
  let prev = performance.now();
  function frame(now){
    const dt = Math.min(0.1, (now-prev)/1000); prev = now;
    if(S.playing) S.current = (S.current + dt*S.speed) % 86400;
    phone.tick(dt);                           // particles have their own looping clock
    if(phone.timeChanged()) update();         // the time-of-day profile moves in 5-minute steps
    else { render(); paint(dt); }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

start();
