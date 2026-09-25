// FlowSense phone data (Teeuwen & Gil 2025, Zenodo 10.5281/zenodo.16794871).
//
// Phone location fixes (GPS, Wi-Fi or fused) from 2024, chained into trips and
// map-matched to Trafikverket's road network; trips are split into (trip, road)
// crossings and 100,000 crossings are sampled at random FOR EACH minimum
// average speed from 0 to 20 km/h. Those nine draws are independent, not
// nested subsets, so sweeping the filter upwards does not remove traffic from
// a fixed sample - it swaps in a different 100,000 crossings, made only by
// trips that fast. The map moves from all movement to motor traffic only.
//
// No time of day and no individual trips are published, so:
//   - particles move in each road's real direction, in proportion to that
//     direction's count; their timing is illustrative
//   - the daily rhythm comes from a chosen time-of-day profile (stage 24)
//
// Layers, each switched on and off on its own (drawn bottom to top):
//   load       crossings per 100 m cell
//   flows      roads, coloured by volume, slow-traffic index or network residual
//   particles  moving particles, thicker on busier roads
//   counts     2023 traffic count sites
import { S } from "./state.js";
import { inflate, lines, pctile } from "./decode.js";
import { rampColor, vramp, lramp, diverge, divergeNet } from "./colors.js";

const FMINW = 0.6, FMAXW = 10;
const PMINW = 1.4, PMAXW = 5;
const V_MS = 120, PERIOD = 12, TRAIL = 0.55, PARTICLES = 45000;
const GROUND = [14, 16, 20];
const PARTICLE = [255, 236, 190];
const COUNTS = [255, 68, 92];        // the 2023 count sites: a red nothing else uses
const THIN = 5;                      // crossings below this cannot be ranked
const SLOW_MAX = 3;                  // slow index colour saturates here (and 1/3)
export const LAYERS = [
  {key:"load",      name:"Traffic heat"},
  {key:"flows",     name:"Street flows"},
  {key:"particles", name:"Moving particles"},
  {key:"counts",    name:"Count sites 2023"},
];
// each colouring asks the street network a different question
export const MODES = [
  {key:"volume", name:"VOLUME",   q:"How busy is this street?"},
  {key:"slow",   name:"SLOW",     q:"How fast is the traffic here?"},
  {key:"lane",   name:"PER LANE", q:"Is this street busy for its size?"},
  {key:"net",    name:"NETWORK",  q:"Is it busier than the city's layout predicts?"},
];
export const modeQuestion = k => (MODES.find(m => m.key === k) || MODES[0]).q;
const fmtN = n => Math.round(n).toLocaleString("en");
const tipStyle = {background:"rgba(14,23,32,.96)", color:"#DCE6F0",
  border:"1px solid #1D2C39", borderRadius:"3px", padding:"10px 12px",
  fontFamily:"'IBM Plex Mono', monospace", fontSize:"13.5px", lineHeight:"1.5"};

let D = null, R = null, DIR = null, LOAD = null, CI = null;
let version = 0, tau = 0, stepKey = "";
const partCache = new Map();         // threshold -> particle set (a few kept)
let loadRows = [], loadMax = 1;

export const ready = () => !!R;
export const thresholds = () => D ? D.thresholds : [0];
export const thLabel = i => { const t = thresholds()[i]; return t ? `≥ ${t} km/h` : "all speeds"; };
export const stats = () => D ? D.stats : null;
const th = () => Math.max(0, Math.min(thresholds().length - 1, S.th));
const cnt = () => R.counts[th()];

// Poisson 95% interval for a sampled count
export function ci(k){
  if(!CI) return [k, k];
  if(k <= CI.max) return [CI.lo[k], CI.hi[k]];
  const s = Math.sqrt(k);                       // normal approximation beyond the table
  return [Math.max(0, k - 1.96*s), k + 1.96*s];
}

export async function load(sweep){
  D = sweep;
  const P = (o, k) => inflate(o[k]);
  const [rc, rn, rcls, slow, slowK, resid, residK] = await Promise.all(
    [P(D.roads,"coords"), P(D.roads,"npts"), P(D.roads,"cls"), P(D.roads,"slow"),
     P(D.roads,"slow_known"), P(D.roads,"resid"), P(D.roads,"resid_known")]);
  const rcounts = await Promise.all(D.roads.counts.map(inflate));
  R = {n:D.roads.n, ...lines(rc, new Uint16Array(rn)), cls:new Uint8Array(rcls),
       counts:rcounts.map(b => new Uint16Array(b)),
       slow:new Uint16Array(slow), slowKnown:new Uint8Array(slowK),
       resid:new Int8Array(resid), residKnown:new Uint8Array(residK),
       col:new Uint8Array(D.roads.n*4), wid:new Float32Array(D.roads.n),
       band:new Uint8Array(D.roads.n), ref:[], laneRef:[]};
  const [lanes, scls] = await Promise.all([P(D.roads,"lanes"), P(D.roads,"scls")]);
  R.lanes = new Uint8Array(lanes);          // 0 = not tagged in OpenStreetMap
  R.scls = new Uint8Array(scls);            // index into D.street_classes, 255 = unknown

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

const roadRef = i => R.ref[i] ?? (R.ref[i] = pctile(R.counts[i], 0.995));
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
    if(c[k] <= 0 || (thin && !S.showThin)){ R.wid[k] = 0; R.col[k*4+3] = 0; continue; }
    const q = Math.min(1, c[k]/ref);
    let col, known = true;
    if(S.mode === "slow"){
      known = !!R.slowKnown[k];
      const idx = R.slow[k]/100;                                  // 1 = city average mix
      col = known ? diverge(Math.max(-1, Math.min(1, Math.log2(Math.max(idx, 1e-3))/Math.log2(SLOW_MAX)))) : [50,62,76];
    } else if(S.mode === "net"){
      known = !!R.residKnown[k];
      col = known ? divergeNet(Math.max(-1, Math.min(1, (R.resid[k]/100) / 0.5))) : [50,62,76];
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
    const a = (S.mode === "volume" ? (70 + 130*q) : (known ? 235 : 70)) / 255 * (thin ? 0.45 : 1);
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
    threshold:0.03, colorRange:range, opacity:S.layers.flows ? 0.75 : 0.95,
    updateTriggers:{getWeight:version}});
  return new deck.ScatterplotLayer({            // older deck builds: the old cells
    id:"load", data:loadRows, getPosition:d=>d.p, getFillColor:d=>d.c,
    radiusUnits:"meters", getRadius:LOAD.cell*0.66, radiusMinPixels:0.8, stroked:false,
    opacity:S.layers.flows ? 0.7 : 1, pickable:true,
    updateTriggers:{getFillColor:version}, parameters:{depthTest:false}});
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
  if(on.load) out.push(heatLayer());
  if(on.flows){
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

function widthLegend(ref){
  let svg = "";
  [0.05,0.25,0.5,1].forEach((q,k)=>{
    const c = vramp(Math.sqrt(q)).map(Math.round), w = FMINW+(FMAXW-FMINW)*q, x = 6+k*54;
    svg += `<line x1="${x}" y1="10" x2="${x+38}" y2="10" stroke="rgb(${c.join(",")})" stroke-width="${w}" stroke-linecap="round"/>
      <text x="${x+19}" y="31" fill="#9DB1C4" font-size="12" text-anchor="middle" font-family="IBM Plex Mono, monospace">${Math.max(1, Math.round(ref*q))}</text>`;
  });
  return `<svg viewBox="0 0 222 42" role="img" aria-label="Crossings scale">${svg}</svg>`;
}
function bar(fn, left, right, label){
  let s = "";
  for(let k=0;k<40;k++){ const c = fn(k/39).map(Math.round);
    s += `<rect x="${k*5.5}" y="4" width="5.7" height="11" fill="rgb(${c.join(",")})"/>`; }
  return `<svg viewBox="0 0 220 40" role="img" aria-label="${label}">${s}
    <text x="0" y="30" fill="#9DB1C4" font-size="12" font-family="IBM Plex Mono, monospace">${left}</text>
    <text x="220" y="30" fill="#9DB1C4" font-size="12" text-anchor="end" font-family="IBM Plex Mono, monospace">${right}</text></svg>`;
}

// the numbers behind the per-lane colour scale
const laneTicks = ref => `<div class="cap" style="margin-top:2px">Scale: ` +
  [0.25, 0.5, 0.75, 1].map(q => Math.max(1, Math.round(ref*q))).join(" · ") +
  ` crossings per lane.</div>`;

export function swatch(key){
  if(key === "particles") return `<span class="sw" style="background:rgb(${PARTICLE.join(",")})"></span>`;
  if(key === "flows"){
    if(S.mode === "slow" || S.mode === "net")
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
  const when = ", whole sample";
  if(key === "particles"){
    const pt = particles();
    return `<div class="cap">Particles travel in each road's <b>real direction of travel</b>, as many as its
      count and thicker the busier it is (${fmtN(pt.particles)} particles at ${thLabel(th())}).</div>`;
  }
  if(key === "flows"){
    if(S.mode === "slow"){
      const s = D.stats.design, rows = s && s.slow_by_class ? Object.entries(s.slow_by_class)
        .sort((a,b) => b[1].median_slow_index - a[1].median_slow_index) : [];
      return bar(t => diverge(-1+2*t), "motor traffic", "slow traffic", "Slow traffic scale") +
        `<div class="cap"><b>How fast the traffic is</b>, not what it is. A road's share of the all-speeds draw
        against its share of the ≥ 20 km/h draw. <b>Ember</b> = relatively more slow movement, <b>violet</b> = fast.
        Slow mixes walking, cycling and cars in congestion — the data carries no mode, so it cannot tell them
        apart. Grey = too few crossings.</div>` +
        (rows.length ? `<table class="rho"><caption>median index, by street type</caption>` +
          rows.slice(0, 4).map(([k, v]) => `<tr><td>${k.replace("_", " ")}</td><td>${v.median_slow_index}</td></tr>`).join("") +
          rows.slice(-2).map(([k, v]) => `<tr><td>${k.replace("_", " ")}</td><td>${v.median_slow_index}</td></tr>`).join("") +
          `</table>` : "");
    }
    if(S.mode === "lane"){
      const s = D.stats.design, rows = s && s.by_class ? Object.entries(s.by_class)
        .sort((a,b) => b[1].median_per_lane - a[1].median_per_lane).slice(0, 6) : [];
      return bar(lramp, "light", "heaviest", "Per-lane scale") + laneTicks(laneRef(th())) +
        `<div class="cap"><b>Crossings per driving lane</b>, so a four-lane road has to carry four times as much
        to look as loaded as a single-lane street. Lane counts come from OpenStreetMap, which tags them on
        ${fmtN(D.stats.roads_with_lanes)} of ${fmtN(D.stats.roads_total)} roads here — 71% of main roads, but few
        residential streets. Grey = no lane count, or too few crossings.</div>` +
        (rows.length ? `<table class="rho"><caption>median per lane, by street type</caption>` +
          rows.map(([k, v]) => `<tr><td>${k.replace("_", " ")}</td><td>${v.median_per_lane}</td></tr>`).join("") +
          `</table>` : "");
    }
    if(S.mode === "net")
      return bar(t => divergeNet(-1+2*t), "quieter", "busier", "Network residual scale") +
        `<div class="cap"><b>Against network position.</b> If everyone drove the shortest way between every pair of
        places, which roads would they be forced onto? That is betweenness centrality on the Trafikverket graph.
        This shows traffic percentile minus centrality percentile: <b>magenta</b> = busier than the layout predicts,
        <b>azure</b> = quieter. Grey = too few crossings to tell.</div>`;
    return widthLegend(roadRef(th())) +
      `<div class="cap"><b>Width and colour</b> = sampled crossings per road, both directions${when},
      at ${thLabel(th())}. The busiest roads are drawn last, over a soft halo, so the main network
      reads through the quiet web around it.</div>`;
  }
  if(key === "load")
    return bar(rampColor, "quiet", "busiest", "Heat scale") +
      `<div class="cap"><b>Which parts of the city carry the traffic.</b> Every sampled crossing is dropped on a
      100 m grid and then blurred, so neighbouring streets add up: bright means a whole area is busy, not one
      road. Which road carries it is the street layer's job — switch <b>Street flows</b> off to read the heat
      on its own.</div>`;
  return `<div class="cap">The <b>red dots</b> are real traffic counters: Trafikverket highway links and
    Göteborg Stad points, 2023. Hover one for its measured vehicles per day — the only true volumes on
    this map.</div>`;
}

export function layerStat(key){
  if(!R) return "";
  if(key === "particles") return fmtN(particles().particles);
  if(key === "flows"){
    const c = cnt(); let n = 0;
    for(let i=0;i<R.n;i++) if(c[i] >= (S.showThin ? 1 : THIN)) n++;
    return fmtN(n);
  }
  if(key === "load") return fmtN(loadRows.length)+" cells";
  return fmtN(D.ground.length);
}

// the speed-filter sweep
export function sweepNote(el){
  if(!el || !D) return;
  const i = th(), reached = D.stats.reached[i];
  el.innerHTML = `<div class="cap"><b>${thLabel(i)}</b> — ${fmtN(D.stats.reached[0])} roads carry
    all-speeds traffic, ${fmtN(reached)} at this filter. Each filter is its <b>own draw of 100,000 crossings</b>
    from the trips that fast, not a subset of the one before, so counts can rise as the filter tightens.
    Raising it moves the map from all movement to motor traffic.</div>`;
}

export function uncertaintyNote(el){
  if(!el || !D) return;
  const s = D.stats;
  el.innerHTML = `<div class="cap">These are <b>100,000 sampled trips</b>, not every trip, spread over
    ${fmtN(s.roads_total)} roads — so most roads got only a handful. ${fmtN(s.roads_thin)} of them
    (${Math.round(100*s.roads_thin/s.roads_total)}%) were crossed fewer than ${THIN} times, which is
    too few to say anything: a road with 4 could really be anywhere between 1 and 10. Those roads are
    ${S.showThin ? "drawn faint" : "hidden"}, and every tooltip gives the range the true value is
    95% likely to sit in. Typical road: <b>±${Math.round(100*s.median_rse)}%</b>.</div>`;
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
    const i = th(), k = R.counts[i][index], [lo, hi] = ci(k);
    const slow = R.slowKnown[index] ? (R.slow[index]/100) : null;
    const res = R.residKnown[index] ? (R.resid[index]/100) : null;
    const lanes = R.lanes[index], scls = D.street_classes[R.scls[index]];
    return {style:tipStyle, html:`<div style="color:#8195A8;font-size:11.5px;letter-spacing:.08em">ROAD · BOTH DIRECTIONS · ${D.speed_classes[R.cls[index]]} KM/H CLASS</div>
      <div style="font-size:20px;margin:5px 0">${fmtN(k)} <span style="font-size:12.5px;color:#9DB1C4">sampled crossings at ${thLabel(i)}</span></div>
      <div style="color:#8195A8">95% range ${lo.toFixed(1)} – ${hi.toFixed(1)}${k < THIN ? " · too few to rank" : ""}</div>
      <div>all speeds: ${fmtN(R.counts[0][index])} · ≥ 20 km/h: ${fmtN(R.counts[R.counts.length-1][index])}</div>
      ${lanes ? `<div>${lanes} lane${lanes > 1 ? "s" : ""}${scls ? " · " + scls.replace("_", " ") : ""} — <b>${(k/lanes).toFixed(1)}</b> crossings per lane</div>`
              : scls ? `<div>${scls.replace("_", " ")} · no lane count in OpenStreetMap</div>` : ""}
      ${slow != null ? `<div>slow index <b>${slow.toFixed(2)}</b>${slow > 1.3 ? " (more slow movement)" : slow < 0.7 ? " (mostly fast traffic)" : ""}</div>` : ""}
      ${res != null ? `<div>vs network position <b>${res > 0 ? "+" : ""}${(100*res).toFixed(0)}</b> percentile points</div>` : ""}`};
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
