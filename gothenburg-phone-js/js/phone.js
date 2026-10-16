// FlowSense phone data (Teeuwen & Gil 2025, Zenodo 10.5281/zenodo.16794871).
//
// Phone location fixes (GPS, Wi-Fi or fused) from 2024, chained into trips and
// map-matched to Trafikverket's road network; trips are split into (trip, road)
// crossings and 100,000 crossings are sampled at random FOR EACH minimum
// average speed from 0 to 20 km/h. Those nine draws are independent, not
// nested subsets, so sweeping the filter upwards does not remove traffic from
// a fixed sample - it swaps in a different 100,000 crossings, made only by
// trips with at least that average speed.
//
// No time of day and no individual trips are published, so:
//   - particles move in each road's real direction, in proportion to that
//     direction's count; their timing is illustrative
//   - the daily rhythm comes from a chosen time-of-day profile (stage 24)
//
// Layers, each switched on and off on its own (drawn bottom to top):
//   load       crossings per 100 m cell
//   flows      roads, coloured by volume, speed (slow-traffic index) or per lane
//   particles  moving particles, thicker on busier roads
//   counts     2023 traffic count sites
import { S } from "./state.js";
import { inflate, lines, pctile } from "./decode.js";
import { rampColor, vramp, lramp, diverge } from "./colors.js";

const FMINW = 0.6, FMAXW = 10;
const PMINW = 1.4, PMAXW = 5;
const V_MS = 120, PERIOD = 12, TRAIL = 0.55, PARTICLES = 45000;
const GROUND = [14, 16, 20];
const PARTICLE = [255, 236, 190];
const COUNTS = [255, 68, 92];        // the 2023 count sites: a red nothing else uses
const THIN = 5;                      // crossings below this cannot be ranked
const SLOW_MAX = 3;                  // slow index colour saturates here (and 1/3)
// VOLUME classes: six equal intervals of raw all-speeds crossings, from 1 to the
// busiest road (step = ceil(max / 6)), nothing divided or rescaled. A road's
// colour and width say which interval its own count falls in.
const VSTYLE = [[0.8, 0.12], [1.4, 0.30], [2.4, 0.48], [4, 0.66], [6.5, 0.84], [9, 1]];  // width, colour
let VCLASS = [], VSTEP = 1;
function buildClasses(max){
  VSTEP = Math.max(1, Math.ceil(max / VSTYLE.length));
  VCLASS = VSTYLE.map(([w, t], j) => ({lo:j*VSTEP + 1, hi:(j+1)*VSTEP, w, col:vramp(t)}));
}
const vclass = k => Math.min(VCLASS.length - 1, Math.floor((k - 1) / VSTEP));
// a class's colour as drawn: blended into the dark ground, brighter for higher classes
function vshade(j, faint){
  const c = VCLASS[j].col, a = (70 + 130 * j / (VCLASS.length - 1)) / 255 * (faint ? 0.45 : 1);
  return [0, 1, 2].map(n => Math.round(GROUND[n] + (c[n] - GROUND[n]) * a));
}
// the first row is whatever the chosen view paints; the rest are extras
export const LAYERS = [
  {key:"flows",     name:"Street flows"},
  {key:"particles", name:"Moving particles"},
  {key:"counts",    name:"Count sites 2023"},
];
export const layerName = key => key === "flows" && isHeat() ? "Traffic heat"
  : (LAYERS.find(l => l.key === key) || {}).name;
// each view asks the same data a different question. The first three colour the
// street network; HEAT drops the streets and shows a density surface instead.
export const MODES = [
  {key:"volume", name:"VOLUME",   q:"How many sampled trips crossed this road?"},
  {key:"slow",   name:"SPEED",    q:"Is this road's share of the sampled trips bigger at all speeds or at ≥ 20 km/h?"},
  {key:"lane",   name:"PER LANE", q:"How many sampled trips crossed this road per driving lane?"},
  {key:"heat",   name:"HEAT",     q:"Where do the sampled trips cross most often?"},
];
export const modeQuestion = k => (MODES.find(m => m.key === k) || MODES[0]).q;
export const isHeat = () => S.mode === "heat";
const fmtN = n => Math.round(n).toLocaleString("en");
const tipStyle = {background:"rgba(14,23,32,.96)", color:"#DCE6F0",
  border:"1px solid #1D2C39", borderRadius:"3px", padding:"10px 12px",
  fontFamily:"'IBM Plex Mono', monospace", fontSize:"13.5px", lineHeight:"1.5"};

let D = null, R = null, DIR = null, LOAD = null, CI = null, NV = null;
let version = 0, tau = 0, stepKey = "";
const partCache = new Map();         // threshold -> particle set (a few kept)
let loadRows = [], loadMax = 1;

export const ready = () => !!R;
export const thresholds = () => D ? D.thresholds : [0];
export const thLabel = i => { const t = thresholds()[i]; return t ? `≥ ${t} km/h` : "all speeds"; };
export const stats = () => D ? D.stats : null;
// the speed filter belongs to the SPEED view only; every other view reads the
// all-speeds draw (trajcount_minavgspeed0, the raw FlowSense count)
export const filterOn = () => S.mode === "slow";
// views without the speed, sampling and count-site panels: every road with a count is drawn
export const plainView = () => S.mode === "volume" || S.mode === "lane";
const th = () => filterOn() ? Math.max(0, Math.min(thresholds().length - 1, S.th)) : 0;
const cnt = () => R.counts[th()];

// Poisson 95% interval for a sampled count
export function ci(k){
  if(!CI) return [k, k];
  if(k <= CI.max) return [CI.lo[k], CI.hi[k]];
  const s = Math.sqrt(k);                       // normal approximation beyond the table
  return [Math.max(0, k - 1.96*s), k + 1.96*s];
}

// NVDB data per road, looked up by RLID through Trafikverket's API (stage 32)
export function loadNvdb(lut){ NV = lut; }
const nv = (k, i) => NV && NV.n === R.n ? NV.strings[NV[k][i]] || "" : "";
const esc = s => s.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
// the road's NVDB lines for a tooltip: name, then RLID, road number, limit, manager
function nvdbHtml(i){
  if(!NV || NV.n !== R.n) return {title:"", lines:""};
  const name = nv("name", i), rlid = nv("rlid", i), road = nv("road", i),
        speed = nv("speed", i), mgr = nv("manager", i);
  const facts = [road && `road ${esc(road)}`, speed && `${esc(speed)} km/h limit`].filter(Boolean).join(" · ");
  return {
    title: name ? `<div style="font-weight:500;font-size:15px">${esc(name)}</div>` : "",
    lines: `<div style="color:#8195A8;margin-top:4px">RLID ${esc(rlid)}${facts ? " · " + facts : ""}</div>` +
      (mgr ? `<div style="color:#8195A8">${esc(mgr)}</div>` : "") +
      `<div style="color:#5F7488;font-size:11.5px">NVDB · Trafikverket</div>`};
}

export async function load(sweep){
  D = sweep;
  const P = (o, k) => inflate(o[k]);
  const [rc, rn, rcls, slow, slowK] = await Promise.all(
    [P(D.roads,"coords"), P(D.roads,"npts"), P(D.roads,"cls"), P(D.roads,"slow"),
     P(D.roads,"slow_known")]);
  const rcounts = await Promise.all(D.roads.counts.map(inflate));
  R = {n:D.roads.n, ...lines(rc, new Uint16Array(rn)), cls:new Uint8Array(rcls),
       counts:rcounts.map(b => new Uint16Array(b)),
       slow:new Uint16Array(slow), slowKnown:new Uint8Array(slowK),
       col:new Uint8Array(D.roads.n*4), wid:new Float32Array(D.roads.n),
       band:new Uint8Array(D.roads.n), ref:[], laneRef:[]};
  const [lanes, scls] = await Promise.all([P(D.roads,"lanes"), P(D.roads,"scls")]);
  R.lanes = new Uint8Array(lanes);          // 0 = not tagged in OpenStreetMap
  R.scls = new Uint8Array(scls);            // index into D.street_classes, 255 = unknown
  buildClasses(R.counts[0].reduce((m, v) => Math.max(m, v), 1));
  const [dc, dn, dcls] = await Promise.all(
    [P(D.directed,"coords"), P(D.directed,"npts"), P(D.directed,"cls")]);
  const dcounts = await Promise.all(D.directed.counts.map(inflate));
  DIR = {n:D.directed.n, ...lines(dc, new Uint16Array(dn)), cls:new Uint8Array(dcls),
         counts:dcounts.map(b => new Uint16Array(b))};

  const lp = await inflate(D.load.pos);
  const [lt, lc] = await Promise.all([
    Promise.all(D.load.totals.map(inflate)), Promise.all(D.load.cls.map(inflate))]);
  LOAD = {n:D.load.ncell, cell:D.load.cell_m, ncl:D.speed_classes.length,
          pos:new Int32Array(lp), totals:lt.map(b => new Uint16Array(b)),
          cls:lc.map(b => new Uint16Array(b)), ref:[]};

  const [clo, chi] = await Promise.all([inflate(D.ci.lo), inflate(D.ci.hi)]);
  CI = {max:D.ci.max, lo:new Float32Array(clo), hi:new Float32Array(chi)};
}

// the raw maximum crossing count (FlowSense trajcount), so the scale reads in
// absolute crossings up to the busiest road instead of a clipped percentile
const roadRef = i => R.ref[i] ?? (R.ref[i] = R.counts[i].reduce((m, v) => Math.max(m, v), 1));
// crossings per lane, where OpenStreetMap tags a lane count
export const perLane = (i, k) => R.lanes[k] ? R.counts[i][k] / R.lanes[k] : NaN;
function laneRef(i){
  if(R.laneRef[i] != null) return R.laneRef[i];
  const v = [];
  for(let k=0;k<R.n;k++) if(R.lanes[k] && R.counts[i][k] >= THIN) v.push(R.counts[i][k]/R.lanes[k]);
  v.sort((a,b) => a-b);
  return (R.laneRef[i] = v.length ? v[Math.floor(0.95*(v.length-1))] : 1);
}
const loadRef = i => LOAD.ref[i] ?? (LOAD.ref[i] = pctile(LOAD.totals[i], 0.995));
const hash = i => { let x = (i+1)*2654435761 % 4294967296; x ^= x >>> 13; x = x*1274126177 % 4294967296; return (x >>> 0)/4294967296; };

// particles for one speed filter; a few filters are kept in memory
function particles(){
  const key = th();
  if(partCache.has(key)) return partCache.get(key);
  const c = DIR.counts[key], pos = DIR.pos, start = DIR.start, ref = pctile(c, 0.995);
  let total = 0; for(let i=0;i<DIR.n;i++) total += c[i];
  const K = PARTICLES / Math.max(1, total);
  const nOf = new Uint16Array(DIR.n);
  let parts = 0, verts = 0;
  for(let i=0;i<DIR.n;i++){
    const n = Math.floor(c[i]*K + hash(i));
    nOf[i] = n; parts += n; verts += n * (start[i+1]-start[i]);
  }
  const Pv = new Float32Array(verts*4), T = new Float32Array(verts*2), SI = new Uint32Array(parts*2+1);
  const pc = new Uint8Array(parts*2), pu = new Float32Array(parts*2), pw = new Float32Array(parts*2);
  let w = 0, p = 0;
  for(let i=0;i<DIR.n;i++){
    const n = nOf[i]; if(!n) continue;
    const a = start[i], b = start[i+1], nv = b-a;
    const cum = new Float32Array(nv);
    for(let k=1;k<nv;k++){
      const lat = pos[(a+k)*2+1] * Math.PI/180;
      const dx = (pos[(a+k)*2]-pos[(a+k-1)*2]) * 111320 * Math.cos(lat);
      const dy = (pos[(a+k)*2+1]-pos[(a+k-1)*2+1]) * 110540;
      cum[k] = cum[k-1] + Math.hypot(dx, dy);
    }
    const width = PMINW + (PMAXW-PMINW) * Math.min(1, c[i]/Math.max(1, ref));
    for(let j=0;j<n;j++){
      const phase = ((j + hash(i*7+3)) / n) * PERIOD, u = hash(i*131 + j*17 + 5);
      for(const shift of [0, PERIOD]){
        pc[p] = DIR.cls[i]; pu[p] = u; pw[p] = width;
        SI[p++] = w;
        for(let k=0;k<nv;k++){
          Pv[(w+k)*2] = pos[(a+k)*2]; Pv[(w+k)*2+1] = pos[(a+k)*2+1];
          T[w+k] = phase + shift + cum[k]/V_MS;
        }
        w += nv;
      }
    }
  }
  SI[p] = w;
  const set = {n:parts*2, particles:parts, ref, cls:pc, u:pu, w:pw,
    data:{length:parts*2, startIndices:SI,
          attributes:{getPath:{value:Pv, size:2}, getTimestamps:{value:T, size:1}}}};
  partCache.set(key, set);
  if(partCache.size > 3) partCache.delete(partCache.keys().next().value);
  return set;
}

// true when the filter or the colouring changed and the map must be rebuilt
export function stateChanged(){
  const k = `${th()}|${S.mode}|${S.showThin}`;
  if(k === stepKey) return false;
  stepKey = k; return true;
}

export function compute(){
  if(!R) return;
  const c = cnt(), i = th(), ref = roadRef(i);
  for(let k=0;k<R.n;k++){
    const thin = c[k] < THIN;
    R.band[k] = 0;
    // every street view draws every road with a count
    if(c[k] <= 0){ R.wid[k] = 0; R.col[k*4+3] = 0; continue; }
    if(S.mode === "volume"){
      // the raw count picks a fixed class (its colour and width). The class's
      // colour is then blended into the dark ground, brighter for higher classes
      // and fainter below 5 crossings, with a soft halo under classes 11+ - the
      // same effects as the other street views
      const j = vclass(c[k]), v = VCLASS[j];
      R.band[k] = j >= 1 ? 2 : c[k] >= THIN ? 1 : 0;   // band 2 gets the halo, and is drawn last
      R.col.set([...vshade(j, thin), 255], k*4);
      R.wid[k] = v.w;
      continue;
    }
    const q = Math.min(1, c[k]/ref);
    let col, known = true;
    if(S.mode === "slow"){
      known = !!R.slowKnown[k];
      const idx = R.slow[k]/100;                                  // 1 = city average mix
      col = known ? diverge(Math.max(-1, Math.min(1, Math.log2(Math.max(idx, 1e-3))/Math.log2(SLOW_MAX)))) : [50,62,76];
    } else if(S.mode === "lane"){
      // linear, not square-rooted: per-lane values bunch up near the top, and
      // the square root pushed most of them into the white end at once
      const pl = perLane(i, k);
      known = Number.isFinite(pl) && c[k] >= THIN;
      col = known ? lramp(Math.min(1, pl/laneRef(i))) : [50,62,76];
    } else {
      col = vramp(Math.sqrt(q));
    }
    // quiet / middle / busy, so the busiest roads are drawn last
    R.band[k] = q >= 0.25 ? 2 : q >= 0.06 ? 1 : 0;
    // solid colour on the dark ground: overlapping road pieces would otherwise
    // stack their transparency into bright beads
    const a = (known ? 235 : 70) / 255 * (thin ? 0.45 : 1);
    R.col.set([GROUND[0]+(col[0]-GROUND[0])*a, GROUND[1]+(col[1]-GROUND[1])*a,
               GROUND[2]+(col[2]-GROUND[2])*a, 255], k*4);
    R.wid[k] = (FMINW + (FMAXW-FMINW)*q) * (thin ? 0.5 : 1);
  }
  loadRows = [];
  const tot = LOAD.totals[i], lref = loadRef(i);
  for(let k=0;k<LOAD.n;k++){
    if(!tot[k]) continue;
    const col = rampColor(Math.sqrt(Math.min(1, tot[k]/lref)));
    loadRows.push({p:[LOAD.pos[k*2]/1e5, LOAD.pos[k*2+1]/1e5],
                   c:[col[0],col[1],col[2],190], w:tot[k], day:tot[k]});
  }
  loadMax = loadRows.reduce((m, r) => Math.max(m, r.w), 1);
  version++;
}

export function tick(dt){ tau += dt; }        // drives the particle loop only

const zoomScale = () => Math.min(3, Math.max(1, 2 ** ((S.zoom - 11) * 0.4)));

// the heat surface: a kernel density of the 100 m cells, weighted by crossings
function heatLayer(){
  const range = [0.1, 0.3, 0.5, 0.7, 0.85, 1].map(t => rampColor(t).map(Math.round));
  // a wide kernel on purpose: the crossings sit on roads, so a tight radius
  // just traces the street network and reads as a blurred copy of it. Wide, it
  // answers a different question - which PARTS of the city carry the traffic.
  if(deck.HeatmapLayer) return new deck.HeatmapLayer({
    id:"load", data:loadRows, getPosition:d=>d.p, getWeight:d=>d.w,
    aggregation:"SUM", radiusPixels:S.zoom > 13 ? 60 : 45, intensity:1.2,
    threshold:0.03, colorRange:range, opacity:0.95,
    updateTriggers:{getWeight:version}});
  return new deck.ScatterplotLayer({            // older deck builds: the old cells
    id:"load", data:loadRows, getPosition:d=>d.p, getFillColor:d=>d.c,
    radiusUnits:"meters", getRadius:LOAD.cell*0.66, radiusMinPixels:0.8, stroked:false,
    pickable:true, updateTriggers:{getFillColor:version}, parameters:{depthTest:false}});
}

// One PathLayer per band, so the busiest roads are drawn last and read on top
// of the quiet web instead of being buried in whatever order the data has.
function roadBand(id, band, zs, extra = {}){
  return new deck.PathLayer({
    id, data:{length:R.n, startIndices:R.start, attributes:{getPath:{value:R.pos, size:2}}},
    _pathType:"open",
    getColor:(_, {index}) => R.band[index] === band
      ? [R.col[index*4], R.col[index*4+1], R.col[index*4+2], R.col[index*4+3]] : [0,0,0,0],
    getWidth:(_, {index}) => R.band[index] === band ? R.wid[index] : 0,
    widthUnits:"pixels", widthScale:zs, widthMinPixels:0, capRounded:true, jointRounded:true,
    updateTriggers:{getColor:[version, band], getWidth:[version, band]},
    parameters:{depthTest:false}, ...extra});
}

export function layers(){
  if(!R) return [];
  const on = S.layers, zs = zoomScale(), out = [];
  if(on.flows && isHeat()) out.push(heatLayer());
  if(on.flows && !isHeat()){
    // a soft halo under the busiest roads, so the main network carries at a glance
    out.push(new deck.PathLayer({
      id:"roads-halo", data:{length:R.n, startIndices:R.start, attributes:{getPath:{value:R.pos, size:2}}},
      _pathType:"open",
      getColor:(_, {index}) => R.band[index] === 2
        ? [R.col[index*4], R.col[index*4+1], R.col[index*4+2], 38] : [0,0,0,0],
      getWidth:(_, {index}) => R.band[index] === 2 ? R.wid[index] * 3 : 0,
      widthUnits:"pixels", widthScale:zs, widthMinPixels:0, capRounded:true, jointRounded:true,
      updateTriggers:{getColor:version, getWidth:version}, parameters:{depthTest:false}}));
    out.push(roadBand("roads-quiet", 0, zs, {pickable:true}));
    out.push(roadBand("roads-mid", 1, zs, {pickable:true}));
    out.push(roadBand("roads", 2, zs, {pickable:true, autoHighlight:true,
      highlightColor:[255,255,255,90]}));
  }
  if(on.particles){
    const pt = particles();
    out.push(new deck.TripsLayer({
      id:"particles", data:pt.data, opacity:0.9,
      getColor:[...PARTICLE, 235],
      getWidth:(_, {index}) => pt.w[index],
      widthUnits:"pixels", widthScale:Math.min(2.2, zs), widthMinPixels:1,
      capRounded:true, jointRounded:true,
      trailLength:TRAIL, currentTime:(tau % PERIOD) + PERIOD,
      updateTriggers:{getColor:version, getWidth:th()}, parameters:{depthTest:false}}));
  }
  if(on.counts){
    out.push(new deck.ScatterplotLayer({     // a soft glow, so they read on any colouring
      id:"counts-glow", data:D.ground, getPosition:d => [d.lon, d.lat],
      radiusUnits:"pixels", getRadius:9, radiusScale:Math.min(1.5, zs), stroked:false,
      getFillColor:[...COUNTS, 60], parameters:{depthTest:false}}));
    out.push(new deck.ScatterplotLayer({
      id:"counts", data:D.ground, getPosition:d => [d.lon, d.lat],
      radiusUnits:"pixels", getRadius:4, radiusScale:Math.min(1.5, zs), stroked:true,
      getFillColor:[...COUNTS, 245], getLineColor:[12,10,14,235],
      lineWidthUnits:"pixels", getLineWidth:1.4, pickable:true, parameters:{depthTest:false}}));
  }
  return out;
}

// ---------- panel ----------

// VOLUME legend: each class with its raw count range and how many roads fall in it
function volumeLegend(){
  const c = cnt(), n = VCLASS.map(() => 0);
  for(let k=0;k<R.n;k++) if(c[k] > 0) n[vclass(c[k])]++;
  return `<table class="rho"><caption>raw sampled crossings per road</caption>` +
    VCLASS.map((v, j) => {
      const range = v.hi === Infinity ? `${v.lo}+` : v.lo === v.hi ? `${v.lo}` : `${v.lo}–${v.hi}`;
      return `<tr><td><svg width="44" height="12" aria-hidden="true"><line x1="5" y1="6" x2="39" y2="6"
        stroke="rgb(${vshade(j).join(",")})" stroke-width="${v.w}" stroke-linecap="round"/></svg> ${range}</td>
        <td>${fmtN(n[j])} roads</td></tr>`;
    }).join("") + `</table>`;
}
function bar(fn, left, right, label){
  let s = "";
  for(let k=0;k<40;k++){ const c = fn(k/39).map(Math.round);
    s += `<rect x="${k*5.5}" y="4" width="5.7" height="11" fill="rgb(${c.join(",")})"/>`; }
  return `<svg viewBox="0 0 220 40" role="img" aria-label="${label}">${s}
    <text x="0" y="30" fill="#9DB1C4" font-size="12" font-family="IBM Plex Mono, monospace">${left}</text>
    <text x="220" y="30" fill="#9DB1C4" font-size="12" text-anchor="end" font-family="IBM Plex Mono, monospace">${right}</text></svg>`;
}


export function swatch(key){
  if(key === "particles") return `<span class="sw" style="background:rgb(${PARTICLE.join(",")})"></span>`;
  if(key === "flows" && isHeat())
    return `<span class="sw" style="background:linear-gradient(90deg,rgb(${rampColor(0.2).map(Math.round).join(",")}),rgb(${rampColor(1).map(Math.round).join(",")}))"></span>`;
  if(key === "flows"){
    if(S.mode === "slow")
      return `<span class="sw" style="background:linear-gradient(90deg,rgb(${diverge(-1).map(Math.round).join(",")}),rgb(${diverge(1).map(Math.round).join(",")}))"></span>`;
    if(S.mode === "lane")
      return `<span class="sw" style="background:linear-gradient(90deg,rgb(${lramp(0.25).map(Math.round).join(",")}),rgb(${lramp(1).map(Math.round).join(",")}))"></span>`;
    return `<span class="sw" style="background:linear-gradient(90deg,rgb(${vramp(0.3).map(Math.round).join(",")}),rgb(${vramp(1).map(Math.round).join(",")}))"></span>`;
  }
  if(key === "load") return `<span class="sw" style="background:linear-gradient(90deg,rgb(${rampColor(0.2).map(Math.round).join(",")}),rgb(${rampColor(1).map(Math.round).join(",")}))"></span>`;
  return `<span class="sw" style="background:rgb(${COUNTS.join(",")});border-radius:50%"></span>`;
}

export function layerLegend(key){
  if(!R) return "";
  if(key === "particles"){
    const pt = particles();
    return `<div class="cap">Particles move along each road record's direction in the FlowSense file, as many
      as its count and thicker the higher the count (${fmtN(pt.particles)} particles at ${thLabel(th())}).
      Their speed and timing are not in the data.</div>`;
  }
  if(key === "flows"){
    if(isHeat())
      return bar(rampColor, "lowest", "highest", "Heat scale") +
        `<div class="cap">Each road's crossings are added to every 100 m grid cell it passes through, and the
        cell totals are blurred, so neighbouring cells add up. Brighter = a higher blurred total, relative to
        what is in view. No street network in this view.</div>`;
    if(S.mode === "slow")
      return bar(t => diverge(-1+2*t), "index below 1", "index above 1", "Speed index scale") +
        `<div class="cap"><b>Index above 1 (ember):</b> the road's share of the sampled trips is bigger at
        all speeds than at ≥ 20 km/h.<br><b>Index below 1 (violet):</b> the road's share of the sampled
        trips is bigger at ≥ 20 km/h than at all speeds.<br><b>Grey:</b> no index. Either the road has fewer
        than 5 crossings in both samples, or it has none at ≥ 20 km/h.</div>`;
    if(S.mode === "lane")
      return bar(lramp, "light", "heaviest", "Per-lane scale") +
        `<div class="cap"><b>Per lane:</b> the road's all-speeds crossings divided by its number of driving
        lanes (from OpenStreetMap).<br><b>Light (dark teal):</b> 0 crossings per lane.<br><b>Heaviest
        (yellow):</b> ${fmtN(laneRef(th()))} or more crossings per lane, the value 95% of roads stay under.<br>
        <b>Grey:</b> no lane count in OpenStreetMap, or fewer than 5 crossings.</div>`;
    return volumeLegend();
  }
  return `<div class="cap">The <b>red dots</b> are real traffic counters: Trafikverket highway links and
    Göteborg Stad points, 2023. Hover one for its measured vehicles per day (from the FlowSense ground
    truth files).</div>`;
}

export function layerStat(key){
  if(!R) return "";
  if(key === "particles") return fmtN(particles().particles);
  if(key === "flows"){
    if(isHeat()) return fmtN(loadRows.length)+" cells";
    const c = cnt(); let n = 0;
    for(let i=0;i<R.n;i++) if(c[i] >= 1) n++;
    return fmtN(n);
  }
  return fmtN(D.ground.length);
}

// the speed-filter sweep
export function sweepNote(el){
  if(!el || !D) return;
  el.innerHTML = "";
}

export function uncertaintyNote(el){
  if(!el || !D) return;
  const s = D.stats;
  el.innerHTML = `<div class="cap">Each filter is a random sample of <b>100,000 (trip, road) crossings</b>,
    spread over ${fmtN(s.roads_total)} roads. ${fmtN(s.roads_thin)} of them
    (${Math.round(100*s.roads_thin/s.roads_total)}%) have fewer than ${THIN} crossings at all speeds.</div>`;
}

export function quality(el){
  if(!el || !D) return;
  const gt = D.stats.ground_truth;
  const rho = (k, g) => { const v = gt[g][k]; return v && v.spearman != null ? v.spearman.toFixed(2) : "–"; };
  const row = (label, k) => `<tr><td>${label}</td><td>${rho(k,"all counts")}</td><td>${rho(k,"highway links")}</td><td>${rho(k,"municipal points")}</td></tr>`;
  el.innerHTML = `<table class="rho"><caption>Rank correlation (Spearman)</caption>
    <tr><th></th><th>all</th><th>highway</th><th>local</th></tr>
    ${row("≥ 20 km/h", "phone20_vs_counts")}${row("all speeds", "phone_vs_counts")}</table>
    <div class="cap">How well the phone crossings rank roads like the ${D.ground.length} traffic counts
    (Trafikverket highway links and Göteborg Stad points, 2023). The red dots on the map.</div>`;
}

export function tooltip({layer, object, index}){
  if(!R || !layer || index < 0) return null;
  if(layer.id.startsWith("roads") && layer.id !== "roads-halo"){
    const i = th(), k = R.counts[i][index], [lo, hi] = ci(k), nvd = nvdbHtml(index);
    // VOLUME: the raw FlowSense count at the chosen filter and nothing else (no OSM lanes)
    if(S.mode === "volume")
      return {style:tipStyle, html:`${nvd.title}<div style="color:#8195A8;font-size:11.5px;letter-spacing:.08em">ROAD · BOTH DIRECTIONS</div>
        <div style="font-size:20px;margin:5px 0">${fmtN(k)} <span style="font-size:12.5px;color:#9DB1C4">sampled crossings at ${thLabel(i)} (raw count)</span></div>
        ${nvd.lines}`};
    const slow = R.slowKnown[index] ? (R.slow[index]/100) : null;
    const lanes = R.lanes[index], scls = D.street_classes[R.scls[index]];
    return {style:tipStyle, html:`${nvd.title}<div style="color:#8195A8;font-size:11.5px;letter-spacing:.08em">ROAD · BOTH DIRECTIONS · ${D.speed_classes[R.cls[index]]} KM/H CLASS</div>
      <div style="font-size:20px;margin:5px 0">${fmtN(k)} <span style="font-size:12.5px;color:#9DB1C4">sampled crossings at ${thLabel(i)}</span></div>
      <div style="color:#8195A8">95% range ${lo.toFixed(1)} – ${hi.toFixed(1)}${k < THIN ? " · too few to rank" : ""}</div>
      <div>all speeds: ${fmtN(R.counts[0][index])} · ≥ 20 km/h: ${fmtN(R.counts[R.counts.length-1][index])}</div>
      ${lanes ? `<div>${lanes} lane${lanes > 1 ? "s" : ""}${scls ? " · " + scls.replace("_", " ") : ""} — <b>${(k/lanes).toFixed(1)}</b> crossings per lane</div>`
              : scls ? `<div>${scls.replace("_", " ")} · no lane count in OpenStreetMap</div>` : ""}
      ${slow != null ? `<div>speed index <b>${slow.toFixed(2)}</b> (all-speeds share ÷ ≥ 20 km/h share)</div>` : ""}
      ${nvd.lines}`};
  }
  if(layer.id === "load" && object)
    return {style:tipStyle, html:`<div style="color:#8195A8;font-size:11.5px;letter-spacing:.08em">100 M CELL</div>
      <div style="font-size:20px;margin:5px 0">${fmtN(object.day)} <span style="font-size:12.5px;color:#9DB1C4">sampled crossings at ${thLabel(th())}</span></div>`};
  if(layer.id === "counts" && object)
    return {style:tipStyle, html:`<div style="font-weight:500">${object.name || "Trafikverket link"}</div>
      <div style="color:#8195A8;font-size:11.5px;letter-spacing:.08em">${object.src === "highway" ? "TRAFIKVERKET COUNT" : "GÖTEBORG STAD COUNT"} · 2023</div>
      <div style="font-size:20px;margin:5px 0">${fmtN(object.adt)} <span style="font-size:12.5px;color:#9DB1C4">vehicles / day</span></div>
      <div>${object.phone != null ? fmtN(object.phone) : "–"} sampled phone crossings on this road (all speeds)</div>`};
  return null;
}
