// Entry point: load the data files, set up state, start the clock.
// The JavaScript twin of gothenburg-day/index.html - same look, same
// behaviour, but the data lives in data/ instead of inside the page.
import { S, actions } from "./state.js";
import { b64, decodeSample } from "./decode.js";
import { MODE_COLORS, PURPOSE_COLORS } from "./colors.js";
import { rebuild } from "./trips.js";
import { initLoad } from "./load.js";
import { initFlows, loadFlows, rebuildFlowTrips, computeFlows,
         flows, flowBin, flowLastBin } from "./flows.js";
import { initMap, render } from "./map.js";
import { initUI, renderPanel, paint, refreshActive } from "./ui.js";

const loading = document.getElementById("loading");

async function getJSON(name){
  const r = await fetch("data/" + name);
  if(!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
  return r.json();
}

async function start(){
  if(location.protocol === "file:"){
    loading.innerHTML = "BROWSERS BLOCK DATA FILES OPENED FROM DISK.<br>"+
      "IN THE gothenburg-day-js FOLDER RUN: python serve.py";
    return;
  }

  let PAY, LOAD, TEXT;
  try {
    [PAY, LOAD, TEXT] = await Promise.all([getJSON("anim.json"), getJSON("loadgrid.json"), getJSON("meta.json")]);
  } catch(err) {
    loading.innerHTML = `COULD NOT LOAD THE DATA (${err.message}).<br>RUN pipeline/16_export_js_version.py`;
    return;
  }
  // CARTO basemap key (config.json next to index.html; optional - without it
  // the tiles show an "API KEY REQUIRED" watermark)
  try {
    const r = await fetch("config.json");
    if(r.ok) S.cartoKey = ((await r.json()).cartoApiKey || "").trim();
  } catch(_) { /* no config: tiles without a key */ }
  document.getElementById("subtitle").textContent = TEXT.subtitle;
  document.getElementById("note").innerHTML = TEXT.note;

  // ---------- animation sample ----------
  const mb = b64(PAY.meta), cb = b64(PAY.coords);
  const A = decodeSample(new Int32Array(mb.buffer, mb.byteOffset, PAY.n*S.M), cb.buffer, PAY.n, S.M);
  Object.assign(S, { PAY, N:PAY.n, meta:A.meta, POS:A.pos, TS:A.ts, off:A.off,
                     T0:Math.floor(A.tMin), T1:Math.ceil(A.tMax) });
  S.DIMS = {
    mode:    {names:PAY.modes,    colors:MODE_COLORS,    slot:2},
    purpose: {names:PAY.purposes, colors:PURPOSE_COLORS, slot:4}
  };
  S.on = {mode:new Set(PAY.modes), purpose:new Set(PAY.purposes)};
  S.filt = {
    age:   {names:PAY.ages,   slot:5, sel:new Set(PAY.ages)},
    sex:   {names:PAY.sexes,  slot:6, sel:new Set(PAY.sexes)},
    status:{names:PAY.status, slot:7, sel:new Set(PAY.status)}
  };

  initLoad(LOAD);

  actions.rebuild = () => {
    rebuild();
    renderPanel();
    if(flows){ rebuildFlowTrips(); if(S.showFlows) computeFlows(); }
  };
  actions.render = render;
  actions.paint = paint;

  initMap();
  initUI();

  // ---------- clock ----------
  let prev = performance.now(), acc = 0;
  function frame(now){
    const dt = Math.min(0.1,(now-prev)/1000); prev = now;
    if(S.playing){
      S.current += dt*S.speed;
      if(S.current > S.T1) S.current = S.T0;
      acc += dt;
      if(acc > 0.25){ refreshActive(); acc = 0; }
    }
    if(S.showFlows && flows && !S.flowsWholeDay && flowBin() !== flowLastBin) computeFlows();
    render(); paint();
    requestAnimationFrame(frame);
  }

  actions.rebuild();
  refreshActive();
  loading.remove();
  render(); paint();
  requestAnimationFrame(frame);

  // street flows load and unpack in the background; the button enables when ready
  const fbtn = document.getElementById("flowBtn");
  try {
    const [FP, FSP] = await Promise.all([getJSON("flows.json"), getJSON("flowsample.json")]);
    initFlows(FP, FSP);
    await loadFlows();
    fbtn.disabled = false;
  } catch(err) {
    fbtn.title = "Street flows could not be loaded: " + err.message;
  }
}

start();
