// The right-hand panel, the bottom bar and the daily-rhythm chart.
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
      return {key, b, n:b.querySelector(".n"), body:b.nextElementSibling};
    });
  }
  for(const {key, b, n, body} of layerRows){
    const on = S.layers[key];
    b.setAttribute("aria-pressed", String(on));
    n.textContent = on ? phone.layerStat(key) : "off";
    body.hidden = !on;
    body.innerHTML = on ? phone.layerLegend(key) : "";
  }
}

export function toggleLayer(key){
  S.layers[key] = !S.layers[key];
  update();
}

// panel text that depends on the sample, timing or layers
export function refreshPanel(){
  renderLayers();
  phone.sampleNote($("sampleNote"));
  phone.curve($("curve"));
  phone.quality($("quality"));
}

// recompute the map layers and everything that describes them
export function update(){
  phone.compute();
  refreshPanel();
  render(); paint();
}

// ---------- chart: the city-wide daily rhythm of the chosen profile ----------
let cvs, cx2, curveKey = "", pts = null;
function drawChart(){
  const dpr = window.devicePixelRatio||1;
  const w = cvs.clientWidth, h = cvs.clientHeight;
  cvs.width = w*dpr; cvs.height = h*dpr;
  cx2.setTransform(dpr,0,0,dpr,0,0);
  cx2.clearRect(0,0,w,h);
  const key = `${S.timing}|${S.sample}`;
  if(key !== curveKey){
    curveKey = key;
    pts = S.timing === "none" ? new Array(97).fill(1) : phone.cityCurve(S.timing);
  }
  const top = Math.max(2, ...pts), c = S.timing === "none" ? [129,149,168] : phone.CURVE[S.timing];
  const y = v => h - (v/top)*(h-4);
  cx2.fillStyle = `rgba(${c[0]},${c[1]},${c[2]},.32)`;
  cx2.strokeStyle = `rgba(${c[0]},${c[1]},${c[2]},.95)`; cx2.lineWidth = 1.3;
  cx2.beginPath(); cx2.moveTo(0, h);
  pts.forEach((v,k) => cx2.lineTo(k/96*w, y(v)));
  cx2.lineTo(w, h); cx2.closePath(); cx2.fill();
  cx2.beginPath();
  pts.forEach((v,k) => k ? cx2.lineTo(k/96*w, y(v)) : cx2.moveTo(0, y(v)));
  cx2.stroke();
  const px = ((S.current%86400)/86400)*w;
  cx2.strokeStyle="#DCE6F0"; cx2.lineWidth=1.2;
  cx2.beginPath(); cx2.moveTo(px,0); cx2.lineTo(px,h); cx2.stroke();
}

// ---------- clock ----------
let acc = 0;
export function paint(dt = 1){
  const s = Math.floor(S.current)%86400;
  $("clock").innerHTML =
    String(Math.floor(s/3600)).padStart(2,"0")+":"+
    String(Math.floor((s%3600)/60)).padStart(2,"0")+
    '<span class="z">CET</span>';
  acc += dt;
  if(acc > 0.25){ $("active").textContent = phone.activeText(); acc = 0; }
  drawChart();
}

// ---------- controls ----------
function pressGroup(sel, btn){
  document.querySelectorAll(sel).forEach(o => o.setAttribute("aria-pressed", String(o === btn)));
}

export function initUI(){
  cvs = $("chart");
  cx2 = cvs.getContext("2d");

  document.querySelectorAll("#sampleSeg button").forEach(b => b.addEventListener("click", () => {
    S.sample = b.dataset.s; pressGroup("#sampleSeg button", b); update();
  }));
  document.querySelectorAll("#timingChips .chip").forEach(b => b.addEventListener("click", () => {
    S.timing = b.dataset.t; pressGroup("#timingChips .chip", b); update();
  }));

  cvs.addEventListener("click", e => {
    const r = cvs.getBoundingClientRect();
    S.current = ((e.clientX-r.left)/r.width)*86400;
    update();
  });

  $("play").addEventListener("click", e => {
    S.playing = !S.playing;
    e.currentTarget.textContent = S.playing ? "PAUSE" : "PLAY";
    e.currentTarget.setAttribute("aria-pressed", String(S.playing));
  });
  document.querySelectorAll(".spd").forEach(b => b.addEventListener("click", () => {
    S.speed = +b.dataset.s; pressGroup(".spd", b);
  }));

  // layer switches (the rows are re-rendered, so listen on the container)
  $("layers").addEventListener("click", e => {
    const b = e.target.closest("[data-layer]");
    if(b) toggleLayer(b.dataset.layer);
  });
  window.addEventListener("resize", drawChart);
}
