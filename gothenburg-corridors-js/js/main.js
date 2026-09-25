// Entry point: load the corridor payload, draw the map, wire the panel.
// Stage 26 computes the comparison, stage 27 packs it.
import { S } from "./state.js";
import * as C from "./corridors.js";
import { initMap, render } from "./map.js";
import { initUI, refresh } from "./ui.js";

const loading = document.getElementById("loading");

async function start(){
  if(location.protocol === "file:"){
    loading.innerHTML = "BROWSERS BLOCK DATA FILES OPENED FROM DISK.<br>"+
      "IN THE gothenburg-corridors-js FOLDER RUN: python serve.py";
    return;
  }
  if(typeof DecompressionStream === "undefined"){
    loading.innerHTML = "THIS BROWSER CANNOT UNPACK THE DATA.<br>USE A CURRENT CHROME, EDGE, FIREFOX OR SAFARI.";
    return;
  }
  let J;
  try {
    const r = await fetch("data/corridors.json");
    if(!r.ok) throw new Error("HTTP " + r.status);
    J = await r.json();
  } catch(err) {
    loading.innerHTML = `COULD NOT LOAD THE DATA (${err.message}).<br>RUN pipeline/27_export_corridors.py`;
    return;
  }
  try {
    const r = await fetch("config.json");
    if(r.ok) S.cartoKey = ((await r.json()).cartoApiKey || "").trim();
  } catch(_) { /* no config: tiles without a key */ }

  await C.load(J);
  initMap();
  initUI();
  refresh();
  render();
  loading.remove();
}

start();
