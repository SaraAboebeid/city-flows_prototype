// The right-hand panel and the bottom summary bar.
import { S } from "./state.js";
import * as phone from "./phone.js";
import { render } from "./map.js";

const $ = id => document.getElementById(id);

// the layer switches: one row per layer, its legend underneath while it is on
let layerRows = null;
function renderLayers(){
  const el = $("layers");
  if(!el) return;
  if(!layerRows){                       // built once, so focus survives the updates
    el.innerHTML = phone.LAYERS.map(({key, name}) =>
      `<button class="cat" data-layer="${key}" aria-pressed="true">${phone.swatch(key)}` +
      `<span>${name}</span><span class="n"></span></button><div class="layerbody"></div>`).join("");
    layerRows = phone.LAYERS.map(({key}) => {
      const b = el.querySelector(`[data-layer="${key}"]`);
      return {key, b, body:b.nextElementSibling};
    });
  }
  for(const {key, b, body} of layerRows){
    const on = S.layers[key];
    b.setAttribute("aria-pressed", String(on));
    b.innerHTML = phone.swatch(key) +
      `<span>${phone.LAYERS.find(l => l.key === key).name}</span>` +
      `<span class="n">${on ? phone.layerStat(key) : "off"}</span>`;
    body.hidden = !on;
    body.innerHTML = on ? phone.layerLegend(key) : "";
  }
}

export function toggleLayer(key){
  S.layers[key] = !S.layers[key];
  update();
}

export function refreshPanel(){
  $("modeQ").textContent = phone.modeQuestion(S.mode);
  document.querySelectorAll("#modeSeg button").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.m === S.mode)));
  document.querySelectorAll("#thinChips .chip").forEach(b =>
    b.setAttribute("aria-pressed", String(S.showThin)));
  renderLayers();
  $("thLabel").textContent = phone.thLabel(S.th);
  $("thSlider").value = String(S.th);
  $("sweepBtn").setAttribute("aria-pressed", String(S.sweeping));
  $("sweepBtn").textContent = S.sweeping ? "STOP" : "SWEEP";
  phone.sweepNote($("sweepNote"));
  phone.uncertaintyNote($("uncNote"));
  phone.quality($("quality"));
}

export function update(){
  phone.compute();
  refreshPanel();
  render();
}

// ---------- the speed sweep ----------
let sweepAcc = 0, sweepDir = 1;
export function setThreshold(i){
  S.th = Math.max(0, Math.min(phone.thresholds().length - 1, i));
  update();
}
// called from the animation frame: one step every 0.9 s, bouncing at the ends
export function tickSweep(dt){
  if(!S.sweeping) return false;
  sweepAcc += dt;
  if(sweepAcc < 0.9) return false;
  sweepAcc = 0;
  const last = phone.thresholds().length - 1;
  if(S.th >= last) sweepDir = -1;
  if(S.th <= 0) sweepDir = 1;
  S.th += sweepDir;
  return true;
}

// ---------- controls ----------
function pressGroup(sel, btn){
  document.querySelectorAll(sel).forEach(o => o.setAttribute("aria-pressed", String(o === btn)));
}

export function initUI(){
  document.querySelectorAll("#modeSeg button").forEach(b => b.addEventListener("click", () => {
    S.mode = b.dataset.m; pressGroup("#modeSeg button", b);
    if(!S.layers.flows) S.layers.flows = true;      // the mode is about that layer
    update();
  }));
  document.querySelectorAll("#thinChips .chip").forEach(b => b.addEventListener("click", () => {
    S.showThin = !S.showThin;
    b.setAttribute("aria-pressed", String(S.showThin));
    update();
  }));

  $("thSlider").addEventListener("input", e => {
    S.sweeping = false;
    setThreshold(+e.currentTarget.value);
  });
  $("sweepBtn").addEventListener("click", () => {
    S.sweeping = !S.sweeping;
    refreshPanel();
  });

  // layer switches (the rows are re-rendered, so listen on the container)
  $("layers").addEventListener("click", e => {
    const b = e.target.closest("[data-layer]");
    if(b) toggleLayer(b.dataset.layer);
  });
}
