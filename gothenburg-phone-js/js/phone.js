// FlowSense phone data (Teeuwen & Gil 2025, Zenodo 10.5281/zenodo.16794871).
//
// Phone location fixes (GPS, Wi-Fi or fused) from 2024, chained into trips and
// map-matched to Trafikverket's road network; trips are split into (trip, road)
// crossings and 100,000 crossings are sampled at random per speed filter. Each
// road counts how many sampled trips crossed it, per direction of travel.
// No time of day and no individual trips are published, so:
//   - particles move in each road's real direction, in proportion to that
//     direction's count; their timing is illustrative
//   - the daily rhythm comes from a chosen time-of-day profile (pipeline
//     stage 24), per speed-limit class; volumes stay the phones'
//
// Layers, each switched on and off on its own (drawn bottom to top):
//   load       crossings per 100 m cell (same grid and colours as the synthetic STREET LOAD)
//   flows      grey width = crossings per road, both directions
//   particles  moving particles, thicker on busier roads
//   counts     2023 traffic count sites
// Line widths grow as you zoom in (zoomScale), so streets stay readable up close.
import { S } from "./state.js";
import { inflate, lines, pctile } from "./decode.js";
import { nramp, rampColor } from "./colors.js";

// widths are linear in the count, so the many quiet roads stay thin at city
// zoom and the busy ones stand out; zooming in widens everything (zoomScale)
const FMINW = 0.6, FMAXW = 10;                           // street-flow width, px at city zoom
const PMINW = 1.4, PMAXW = 5;                            // particle width, px at city zoom
const V_MS = 120, PERIOD = 40, TRAIL = 0.55, PARTICLES = 45000;
const QUANTUM = 300;                                     // re-evaluate timing every 5 sim-minutes
const PARTICLE = [255, 236, 190];
export const CURVE = { sthlm_fit: [79, 195, 247], gbg3: [93, 211, 158] };
export const TIMINGS = ["sthlm_fit", "gbg3"];
export const LAYERS = [
  {key:"particles", name:"Moving particles"},
  {key:"flows",     name:"Street flows"},
  {key:"load",      name:"Street load"},
  {key:"counts",    name:"Count sites 2023"},
];
// widths grow with zoom: x1 at city zoom (<= 11), about x3 at street zoom (15)
export const zoomScale = () => Math.min(3, Math.max(1, 2 ** ((S.zoom - 11) * 0.4)));
const fmtN = n => Math.round(n).toLocaleString("en");
const tipStyle = {background:"rgba(14,23,32,.96)", color:"#DCE6F0",
  border:"1px solid #1D2C39", borderRadius:"3px", padding:"10px 12px",
  fontFamily:"'IBM Plex Mono', monospace", fontSize:"11.5px", lineHeight:"1.5"};

let PH = null, TP = null, R = null, DIR = null, LOAD = null;
let version = 0, tau = 0, stepKey = "", F = null, FMAX = 1;
const partCache = {};
let loadRows = [];

const v20 = () => S.sample === "v20";
const obsOf = () => v20() ? R.obs20 : R.obs;
const timing = () => (TP && TP.profiles[S.timing]) ? S.timing : "none";
export const ready = () => !!R;

// speed limit (km/h) -> profile class index
function clsOf(kmh){
  if(!TP || !kmh) return TP ? TP.speed_classes.indexOf(50) : 0;
  let best = 0, d = 1e9;
  TP.speed_classes.forEach((c, i) => { const e = Math.abs(c - kmh); if(e < d){ d = e; best = i; } });
  return best;
}

// factor vs the daily average (mean 1) for one class at time t, interpolated
export function factor(key, c, t){
  if(key === "none" || !TP) return 1;
  const p = TP.profiles[key], v = p.by_class[c], n = p.bins;
  const x = (((t % 86400) + 86400) % 86400) / 86400 * n - 0.5;
  const i0 = Math.floor(x), f = x - i0;
  const a = v[((i0 % n) + n) % n], b = v[(((i0 + 1) % n) + n) % n];
  return (a + (b - a) * f) * n;
}
function refreshFactors(){
  const key = timing(), nc = TP ? TP.speed_classes.length : 1;
  F = new Float32Array(nc);
  for(let c=0;c<nc;c++) F[c] = factor(key, c, S.current);
  FMAX = 1;
  if(key !== "none") for(const v of TP.profiles[key].by_class) for(const s of v) FMAX = Math.max(FMAX, s * TP.profiles[key].bins);
}

export async function load(ph, pv, tp){
  PH = ph; TP = tp && tp.profiles ? tp : null;
  const [c, np, ob, ob20, spd] = await Promise.all(
    [PH.coords, PH.npts, PH.obs, PH.obs20, PH.spd].map(inflate));
  R = {n:PH.n, ...lines(c, new Uint16Array(np)), obs:new Uint16Array(ob), obs20:new Uint16Array(ob20),
       col:new Uint8Array(PH.n*4), wid:new Float32Array(PH.n)};
  R.cls = Uint8Array.from(new Uint8Array(spd), clsOf);
  R.ref = pctile(R.obs, 0.995); R.ref20 = pctile(R.obs20, 0.995);
  R.ground = PH.ground.map(d => ({lon:d.lon, lat:d.lat, adt:d.adt, phone:d.phone, src:d.src, name:d.name}));
  const D = pv.directed, L = pv.load;
  const [dc, dn, da, d2, dcl, lp, la, l2, lca, lc2] = await Promise.all(
    [D.coords, D.npts, D.c_all, D.c_20, D.cls, L.pos, L.all, L.v20, L.cls_all, L.cls_v20].map(inflate));
  DIR = {n:D.n, ...lines(dc, new Uint16Array(dn)), all:new Uint16Array(da), v20:new Uint16Array(d2),
         cls:new Uint8Array(dcl)};
  LOAD = {n:L.ncell, cell:L.cell_m, ncl:pv.speed_classes.length, pos:new Int32Array(lp),
          all:new Uint16Array(la), v20:new Uint16Array(l2),
          cls_all:new Uint16Array(lca), cls_v20:new Uint16Array(lc2)};
  LOAD.refAll = pctile(LOAD.all, 0.995); LOAD.refV20 = pctile(LOAD.v20, 0.995);
  refreshFactors();
}

// deterministic 0..1 jitter, so particles do not march in step
const hash = i => { let x = (i+1)*2654435761 % 4294967296; x ^= x >>> 13; x = x*1274126177 % 4294967296; return (x >>> 0)/4294967296; };

// each directed road gets particles in proportion to its whole-sample count
// (and thicker ones the busier it is); the time-of-day profile decides what
// share of them is lit
function particles(){
  const key = v20() ? "v20" : "all";
  if(partCache[key]) return partCache[key];
  const cnt = DIR[key], pos = DIR.pos, start = DIR.start, ref = pctile(cnt, 0.995);
  let total = 0; for(let i=0;i<DIR.n;i++) total += cnt[i];
  const K = PARTICLES / Math.max(1, total);
  const nOf = new Uint16Array(DIR.n);
  let parts = 0, verts = 0;
  for(let i=0;i<DIR.n;i++){
    const n = Math.floor(cnt[i]*K + hash(i));
    nOf[i] = n; parts += n; verts += n * (start[i+1]-start[i]);
  }
  // every particle twice (phase and phase + PERIOD) so the loop has no seam
  const P = new Float32Array(verts*4), T = new Float32Array(verts*2), SI = new Uint32Array(parts*2+1);
  const pc = new Uint8Array(parts*2), pu = new Float32Array(parts*2), pw = new Float32Array(parts*2);
  let w = 0, p = 0;
  for(let i=0;i<DIR.n;i++){
    const n = nOf[i]; if(!n) continue;
    const a = start[i], b = start[i+1], nv = b-a;
    const width = PMINW + (PMAXW-PMINW) * Math.min(1, cnt[i]/ref);
    const cum = new Float32Array(nv);
    for(let k=1;k<nv;k++){
      const lat = pos[(a+k)*2+1] * Math.PI/180;
      const dx = (pos[(a+k)*2]-pos[(a+k-1)*2]) * 111320 * Math.cos(lat);
      const dy = (pos[(a+k)*2+1]-pos[(a+k-1)*2+1]) * 110540;
      cum[k] = cum[k-1] + Math.hypot(dx, dy);
    }
    for(let j=0;j<n;j++){
      const phase = ((j + hash(i*7+3)) / n) * PERIOD, u = hash(i*131 + j*17 + 5);
      for(const shift of [0, PERIOD]){
        pc[p] = DIR.cls[i]; pu[p] = u; pw[p] = width;
        SI[p++] = w;
        for(let k=0;k<nv;k++){
          P[(w+k)*2] = pos[(a+k)*2]; P[(w+k)*2+1] = pos[(a+k)*2+1];
          T[w+k] = phase + shift + cum[k]/V_MS;
        }
        w += nv;
      }
    }
  }
  SI[p] = w;
  return (partCache[key] = {n:parts*2, particles:parts, ref, cls:pc, u:pu, w:pw, data:{length:parts*2, startIndices:SI,
    attributes:{getPath:{value:P, size:2}, getTimestamps:{value:T, size:1}}}});
}

// true when the 5-minute step, timing source or sample changed
export function timeChanged(){
  const k = `${timing()}|${S.sample}|${Math.floor(S.current / QUANTUM)}`;
  if(k === stepKey) return false;
  stepKey = k; return true;
}

export function compute(){
  if(!R) return;
  refreshFactors();
  const obs = obsOf();
  // grey widths, as in the synthetic STREET FLOWS; at rush hour the busiest
  // roads saturate at full width
  const ref = v20() ? R.ref20 : R.ref;
  for(let i=0;i<R.n;i++){
    const o = obs[i] * F[R.cls[i]];
    if(o <= 0){ R.wid[i] = 0; R.col[i*4+3] = 0; continue; }
    const q = Math.min(1, o/ref), c = nramp(Math.sqrt(q));
    R.col.set([c[0],c[1],c[2],70+Math.round(130*q)], i*4);
    R.wid[i] = FMINW + (FMAXW-FMINW)*q;
  }
  // load cells, as in the synthetic STREET LOAD
  loadRows = [];
  const tot = v20() ? LOAD.v20 : LOAD.all, cl = v20() ? LOAD.cls_v20 : LOAD.cls_all;
  const lref = v20() ? LOAD.refV20 : LOAD.refAll;
  for(let i=0;i<LOAD.n;i++){
    if(!tot[i]) continue;
    let v = 0;
    for(let c=0;c<LOAD.ncl;c++) v += cl[i*LOAD.ncl+c] * F[c];
    if(v <= 0) continue;
    const col = rampColor(Math.sqrt(Math.min(1, v/lref)));
    loadRows.push({p:[LOAD.pos[i*2]/1e5, LOAD.pos[i*2+1]/1e5], c:[col[0],col[1],col[2],190], day:tot[i]});
  }
  version++;
}

export function tick(dt){ if(S.playing) tau += dt; }

// bottom to top: load, flows, particles, counts
export function layers(){
  if(!R) return [];
  const on = S.layers, zs = zoomScale(), out = [];
  if(on.load) out.push(new deck.ScatterplotLayer({
    id:"load", data:loadRows, getPosition:d=>d.p, getFillColor:d=>d.c,
    radiusUnits:"meters", getRadius:LOAD.cell*0.66, radiusMinPixels:0.8, stroked:false,
    opacity: on.flows || on.particles ? 0.7 : 1,
    pickable:true, updateTriggers:{getFillColor:version, getPosition:version},
    parameters:{depthTest:false}}));
  if(on.flows) out.push(new deck.PathLayer({
    id:"roads", data:{length:R.n, startIndices:R.start, attributes:{getPath:{value:R.pos, size:2}}},
    _pathType:"open",
    getColor:(_, {index}) => [R.col[index*4], R.col[index*4+1], R.col[index*4+2], R.col[index*4+3]],
    getWidth:(_, {index}) => R.wid[index],
    widthUnits:"pixels", widthScale:zs, widthMinPixels:0, capRounded:true, jointRounded:true,
    pickable:true, autoHighlight:true, highlightColor:[255,255,255,90],
    updateTriggers:{getColor:version, getWidth:version}, parameters:{depthTest:false}}));
  if(on.particles){
    const pt = particles(), lit = new Float32Array(F.length);
    for(let c=0;c<F.length;c++) lit[c] = F[c] / FMAX;
    out.push(new deck.TripsLayer({
      id:"particles", data:pt.data, opacity:0.9,
      getColor:(_, {index}) => pt.u[index] < lit[pt.cls[index]] ? [...PARTICLE, 235] : [0,0,0,0],
      getWidth:(_, {index}) => pt.w[index],
      widthUnits:"pixels", widthScale:Math.min(2.2, zs), widthMinPixels:1, capRounded:true, jointRounded:true,
      trailLength:TRAIL, currentTime:(tau % PERIOD) + PERIOD,
      updateTriggers:{getColor:version, getWidth:S.sample}, parameters:{depthTest:false}}));
  }
  if(on.counts) out.push(new deck.ScatterplotLayer({
    id:"counts", data:R.ground, getPosition:d => [d.lon, d.lat],
    radiusUnits:"pixels", getRadius:3.8, radiusScale:Math.min(1.5, zs), stroked:true,
    getFillColor:[220,230,240,210], getLineColor:[8,13,19,230], lineWidthUnits:"pixels", getLineWidth:1.2,
    pickable:true, parameters:{depthTest:false}}));
  return out;
}

// ---------- panel ----------
// city-wide curve of a profile: speed classes weighted by their crossings
export function cityCurve(key){
  const nc = TP.speed_classes.length, w = new Float64Array(nc), obs = obsOf();
  for(let i=0;i<R.n;i++) w[R.cls[i]] += obs[i];
  const tot = w.reduce((a,b)=>a+b, 0) || 1, pts = [];
  for(let k=0;k<=96;k++){
    let v = 0;
    for(let c=0;c<nc;c++) if(w[c]) v += (w[c]/tot) * factor(key, c, k*900);
    pts.push(v);
  }
  return pts;
}

export function curve(el){
  if(!el || !TP) return;
  const W = 220, H = 70, x = k => 4 + k/96*(W-8);
  const curves = Object.fromEntries(TIMINGS.map(k => [k, cityCurve(k)]));
  const top = Math.max(2, ...TIMINGS.flatMap(k => curves[k]));
  const y = v => H - 12 - v/top*(H-20), active = timing();
  let svg = `<line x1="4" y1="${y(1)}" x2="${W-4}" y2="${y(1)}" stroke="#55697C" stroke-dasharray="2 3" stroke-width="1"/>
    <text x="${W-4}" y="${y(1)-3}" fill="#55697C" font-size="8.5" text-anchor="end" font-family="IBM Plex Mono, monospace">daily average</text>`;
  TIMINGS.forEach(k => {
    const on = k === active, c = CURVE[k];
    const d = curves[k].map((v,i) => `${i?"L":"M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
    svg += `<path d="${d}" fill="none" stroke="rgb(${c.join(",")})" stroke-width="${on?2:1}" stroke-opacity="${on?1:0.45}" stroke-linejoin="round"/>`;
  });
  const px = x((((S.current % 86400)+86400)%86400)/900);
  svg += `<line x1="${px}" y1="4" x2="${px}" y2="${H-12}" stroke="#DCE6F0" stroke-width="1.1"/>`;
  ["00","06","12","18","24"].forEach((l,i) =>
    svg += `<text x="${x(i*24)}" y="${H-1}" fill="#55697C" font-size="8.5" text-anchor="${i===0?"start":i===4?"end":"middle"}" font-family="IBM Plex Mono, monospace">${l}</text>`);
  const now = active === "none" ? null
    : cityCurve(active)[Math.min(96, Math.round((((S.current%86400)+86400)%86400)/900))];
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Time-of-day profiles">${svg}</svg>
    <div class="cap">${TIMINGS.map(k => `<span style="white-space:nowrap"><i style="display:inline-block;width:9px;height:2px;vertical-align:3px;margin-right:4px;background:rgb(${CURVE[k].join(",")})"></i>${TP.profiles[k].label}</span>`).join(" &nbsp;")}</div>
    <div class="cap">${now == null ? "No timing: whole-sample totals — the clock does not change the map."
      : `<b>Now:</b> ${now.toFixed(2)}× the daily average. Rhythm: ${TP.profiles[active].source}. Volumes are the phones'.`}</div>`;
}

function widthLegend(ref, ramp){
  let svg = "";
  [0.05,0.25,0.5,1].forEach((q,k)=>{
    const v = ref*q, c = ramp(Math.sqrt(q)).map(Math.round), w = FMINW+(FMAXW-FMINW)*q, x = 6+k*54;
    svg += `<line x1="${x}" y1="10" x2="${x+38}" y2="10" stroke="rgb(${c.join(",")})" stroke-width="${w}" stroke-linecap="round"/>
      <text x="${x+19}" y="31" fill="#8195A8" font-size="10" text-anchor="middle" font-family="IBM Plex Mono, monospace">${Math.max(1, Math.round(v))}</text>`;
  });
  return `<svg viewBox="0 0 222 36" role="img" aria-label="Crossings scale">${svg}</svg>`;
}
function rampLegend(){
  let bars = "";
  for(let k=0;k<40;k++){ const c = rampColor(k/39).map(Math.round);
    bars += `<rect x="${k*5.5}" y="4" width="5.7" height="11" fill="rgb(${c.join(",")})"/>`; }
  return `<svg viewBox="0 0 220 34" role="img" aria-label="Load scale">${bars}
    <text x="0" y="30" fill="#8195A8" font-size="10" font-family="IBM Plex Mono, monospace">few</text>
    <text x="220" y="30" fill="#8195A8" font-size="10" text-anchor="end" font-family="IBM Plex Mono, monospace">busiest</text></svg>`;
}

function particleLegend(ref){
  let svg = "";
  [0.05,0.25,0.5,1].forEach((q,k)=>{
    const w = PMINW+(PMAXW-PMINW)*q, x = 6+k*54;
    svg += `<line x1="${x}" y1="10" x2="${x+38}" y2="10" stroke="rgb(${PARTICLE.join(",")})" stroke-width="${w}" stroke-linecap="round"/>
      <text x="${x+19}" y="31" fill="#8195A8" font-size="10" text-anchor="middle" font-family="IBM Plex Mono, monospace">${Math.max(1, Math.round(ref*q))}</text>`;
  });
  return `<svg viewBox="0 0 222 36" role="img" aria-label="Particle width scale">${svg}</svg>`;
}

// the little swatch in front of each layer's switch
export function swatch(key){
  if(key === "particles") return `<span class="sw" style="background:rgb(${PARTICLE.join(",")})"></span>`;
  if(key === "flows") return `<span class="sw" style="background:rgb(${nramp(0.8).map(Math.round).join(",")})"></span>`;
  if(key === "load") return `<span class="sw" style="background:linear-gradient(90deg,rgb(${rampColor(0.2).map(Math.round).join(",")}),rgb(${rampColor(1).map(Math.round).join(",")}))"></span>`;
  return `<span class="sw" style="background:rgb(220,230,240);border-radius:50%"></span>`;
}

// legend shown under a layer's switch while it is on
export function layerLegend(key){
  if(!R) return "";
  const timed = timing() !== "none", when = timed ? ", at this time of day" : ", whole sample";
  if(key === "particles"){
    const pt = particles();
    return particleLegend(pt.ref) + `<div class="cap">Sampled crossings per road and direction. Particles travel in each
      road's real direction, as many as its count and thicker the busier it is (${fmtN(pt.particles)} particles${timed
      ? "; how many are lit follows the time-of-day profile" : ""}). <b>Timing and individual trips are illustrative.</b></div>`;
  }
  if(key === "flows")
    return widthLegend(v20() ? R.ref20 : R.ref, nramp) +
      `<div class="cap"><b>Grey width</b> = sampled crossings per road, both directions${when}.</div>`;
  if(key === "load")
    return rampLegend() + `<div class="cap">Sampled crossings per 100 m cell${when}.</div>`;
  return `<div class="cap">Trafikverket highway links and Göteborg Stad points, 2023. Hover a dot for its
    vehicles per day.</div>`;
}

// the count on the right of each layer's switch
export function layerStat(key){
  if(!R) return "";
  if(key === "particles"){
    const pt = particles(); let lit = 0;
    for(let i=0;i<pt.n;i+=2) if(pt.u[i] < F[pt.cls[i]] / FMAX) lit++;    // originals, not loop copies
    return fmtN(lit);
  }
  if(key === "flows"){
    const obs = obsOf(); let n = 0;
    for(let i=0;i<R.n;i++) if(obs[i] * F[R.cls[i]] > 0) n++;
    return fmtN(n);
  }
  if(key === "load") return fmtN(loadRows.length);
  return fmtN(R.ground.length);
}

export function sampleNote(el){
  if(!el) return;
  el.innerHTML = v20()
    ? `<b>≥ 20 km/h:</b> only trips averaging at least 20 km/h — mostly motor traffic. A separate draw of 100,000 road crossings.`
    : `<b>All speeds:</b> every trip, including walking and cycling. A draw of 100,000 road crossings.`;
}

export function quality(el){
  if(!el || !PH) return;
  const gt = PH.stats.ground_truth;
  const rho = (k, g) => { const v = gt[g][k]; return v && v.spearman != null ? v.spearman.toFixed(2) : "–"; };
  const row = (label, k) => `<tr><td>${label}</td><td>${rho(k,"all counts")}</td><td>${rho(k,"highway links")}</td><td>${rho(k,"municipal points")}</td></tr>`;
  el.innerHTML = `<table class="rho"><caption>Rank correlation (Spearman)</caption>
    <tr><th></th><th>all</th><th>highway</th><th>local</th></tr>
    ${row("≥ 20 km/h", "phone20_vs_counts")}${row("all speeds", "phone_vs_counts")}</table>
    <div class="cap">How well the phone crossings rank roads like the ${PH.ground.length} traffic counts
    (Trafikverket highway links and Göteborg Stad points, 2023). White dots on the map.</div>`;
}

export function activeText(){
  const on = S.layers, parts = [];
  if(on.particles) parts.push(layerStat("particles")+" particles moving");
  if(on.flows) parts.push(layerStat("flows")+" roads");
  if(on.load) parts.push(layerStat("load")+" cells");
  if(!parts.length) return on.counts ? R.ground.length+" count sites" : "all layers off";
  return parts.join(" · ") + (timing() === "none" ? " · whole sample" : "");
}

export function tooltip({layer, object, index}){
  if(!R || !layer || index < 0) return null;
  const timed = timing() !== "none";
  if(layer.id === "roads"){
    const f = F[R.cls[index]];
    return {style:tipStyle, html:`<div style="color:#8195A8;font-size:10px;letter-spacing:.08em">ROAD · BOTH DIRECTIONS · ${TP.speed_classes[R.cls[index]]} KM/H CLASS</div>
      <div style="font-size:18px;margin:4px 0">${fmtN(R.obs[index])} <span style="font-size:11px;color:#8195A8">sampled crossings, all speeds</span></div>
      <div>${fmtN(R.obs20[index])} in the ≥ 20 km/h sample (a separate draw)</div>
      ${timed ? `<div>now: ${f.toFixed(2)}× its daily average</div>` : ""}`};
  }
  if(layer.id === "load" && object){
    return {style:tipStyle, html:`<div style="color:#8195A8;font-size:10px;letter-spacing:.08em">100 M CELL</div>
      <div style="font-size:18px;margin:4px 0">${fmtN(object.day)} <span style="font-size:11px;color:#8195A8">sampled crossings, whole sample</span></div>`};
  }
  if(layer.id === "counts" && object){
    const d = object;
    return {style:tipStyle, html:`<div style="font-weight:500">${d.name || "Trafikverket link"}</div>
      <div style="color:#8195A8;font-size:10px;letter-spacing:.08em">${d.src === "highway" ? "TRAFIKVERKET COUNT" : "GÖTEBORG STAD COUNT"} · 2023</div>
      <div style="font-size:18px;margin:4px 0">${fmtN(d.adt)} <span style="font-size:11px;color:#8195A8">vehicles / day</span></div>
      <div>${d.phone != null ? fmtN(d.phone) : "–"} sampled phone crossings on this road (all speeds)</div>`};
  }
  return null;
}
