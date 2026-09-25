// The corridor comparison (pipeline stages 26 and 27).
//
// A corridor is every drivable segment carrying one OSM street name. Both
// sources are averaged along it, weighted by segment length:
//    synthetic   car trips per day        (GAPSIM 2019, residents only)
//    phones      sampled road crossings   (FlowSense 2024, 100,000 crossings)
// They share no unit, so what is compared is each corridor's SHARE of the city
// total (per mille of flow x length) and the ranks. DIFFERENCE colours the
// log2 of those two shares: violet = the model has less than the phones there,
// ember = more.
import { S } from "./state.js";
import { inflate, lines } from "./decode.js";
import { framp, rampColor, diverge } from "./colors.js";

const RATIO_MAX = 4;             // a 16x share difference saturates the colour
const MINW = 0.7, MAXW = 7;
const fmtN = n => Math.round(n).toLocaleString("en");
const tipStyle = {background:"rgba(14,23,32,.96)", color:"#DCE6F0",
  border:"1px solid #1D2C39", borderRadius:"3px", padding:"10px 12px",
  fontFamily:"'IBM Plex Mono', monospace", fontSize:"11.5px", lineHeight:"1.5"};

let D = null, R = null, cidx = null, COL = null, WID = null, version = 0;
export const ready = () => !!R;
export const corridor = i => (D && i >= 0 && i < D.corridors.length) ? D.corridors[i] : null;
export const all = () => D ? D.corridors : [];
export const stats = () => D ? D.stats : null;
export const minCross = () => D ? D.min_crossings : 20;
const well = c => c.cross >= minCross();

export async function load(json){
  D = json;
  const [co, np, ci] = await Promise.all([D.coords, D.npts, D.cidx].map(inflate));
  R = {n:D.n, ...lines(co, new Uint16Array(np))};
  cidx = new Uint16Array(ci);
  // width scale: the 95th percentile of what the phones saw on a corridor
  const v = D.corridors.filter(well).map(c => c.ph20 || 0).sort((a,b) => a-b);
  R.ref = v.length ? v[Math.floor(0.95*(v.length-1))] : 1;
  const s = D.corridors.map(c => c.syn || 0).sort((a,b) => a-b);
  R.refSyn = s.length ? s[Math.floor(0.95*(s.length-1))] : 1;
  paint();
}

// one colour and width per corridor, from the current mode
export function paint(){
  const C = D.corridors, n = C.length;
  COL = new Uint8Array(n*4); WID = new Float32Array(n);
  C.forEach((c, i) => {
    const ok = !S.onlyWell || well(c);
    let col, q;
    if(S.colorBy === "syn"){
      q = Math.min(1, (c.syn || 0) / (R.refSyn || 1));
      col = rampColor(Math.sqrt(q));
    } else if(S.colorBy === "phone"){
      q = Math.min(1, (c.ph20 || 0) / (R.ref || 1));
      col = framp(Math.sqrt(q));
    } else {
      q = Math.min(1, (c.ph20 || 0) / (R.ref || 1));
      col = diverge(Math.max(-1, Math.min(1, (c.ratio || 0) / RATIO_MAX)));
    }
    const a = ok ? (S.colorBy === "ratio" ? 190 + Math.round(55*q) : 120 + Math.round(120*q)) : 28;
    COL.set([col[0], col[1], col[2], a], i*4);
    WID[i] = (ok ? 1 : 0.5) * (MINW + (MAXW-MINW) * Math.sqrt(q));
  });
  version++;
}

// widths grow as you zoom in, as in the phone dashboard
const zoomScale = () => Math.min(3, Math.max(1, 2 ** ((S.view.zoom - 11) * 0.4)));

export function layers(){
  if(!R) return [];
  const zs = zoomScale(), out = [];
  const path = (id, extra) => new deck.PathLayer({
    id, data:{length:R.n, startIndices:R.start, attributes:{getPath:{value:R.pos, size:2}}},
    _pathType:"open", widthUnits:"pixels", widthScale:zs, widthMinPixels:0.4,
    capRounded:true, jointRounded:true, parameters:{depthTest:false}, ...extra});
  out.push(path("corridors", {
    getColor:(_, {index}) => { const k = cidx[index]*4;
      return [COL[k], COL[k+1], COL[k+2], COL[k+3]]; },
    getWidth:(_, {index}) => WID[cidx[index]],
    pickable:true, autoHighlight:true, highlightColor:[255,255,255,90],
    updateTriggers:{getColor:version, getWidth:version}}));
  if(S.selected >= 0) out.push(path("selected", {
    getColor:(_, {index}) => cidx[index] === S.selected ? [255,255,255,235] : [0,0,0,0],
    getWidth:(_, {index}) => cidx[index] === S.selected ? WID[cidx[index]] + 2.5 : 0,
    updateTriggers:{getColor:S.selected, getWidth:[S.selected, version]}}));
  if(S.showCounts) out.push(new deck.ScatterplotLayer({
    id:"counts", data:D.ground, getPosition:d => [d.lon, d.lat],
    radiusUnits:"pixels", getRadius:3.6, radiusScale:Math.min(1.5, zs), stroked:true,
    getFillColor:[220,230,240,210], getLineColor:[8,13,19,230],
    lineWidthUnits:"pixels", getLineWidth:1.2, pickable:true, parameters:{depthTest:false}}));
  return out;
}

// the corridor under the cursor, or -1
export const pick = info =>
  (info && info.layer && info.layer.id === "corridors" && info.index >= 0) ? cidx[info.index] : -1;

// ---------- panel ----------
function bar(fn, left, mid, right, label){
  let s = "";
  for(let k=0;k<40;k++){ const c = fn(k/39).map(Math.round);
    s += `<rect x="${k*5.5}" y="4" width="5.7" height="11" fill="rgb(${c.join(",")})"/>`; }
  return `<svg viewBox="0 0 220 34" role="img" aria-label="${label}">${s}
    <text x="0" y="30" fill="#8195A8" font-size="9.5" font-family="IBM Plex Mono, monospace">${left}</text>
    ${mid ? `<text x="110" y="30" fill="#DCE6F0" font-size="9.5" text-anchor="middle" font-family="IBM Plex Mono, monospace">${mid}</text>` : ""}
    <text x="220" y="30" fill="#8195A8" font-size="9.5" text-anchor="end" font-family="IBM Plex Mono, monospace">${right}</text></svg>`;
}

export function legend(el){
  if(!el || !R) return;
  if(S.colorBy === "ratio")
    el.innerHTML = bar(t => diverge(-1+2*t), "model misses", "", "model over-loads", "Difference scale") +
      `<div class="cap"><b>Violet</b> = the corridor carries a smaller share of the model's traffic than of the
      phones' — the model misses it. <b>Ember</b> = the model over-loads it. Fully violet also covers corridors
      with <b>no synthetic traffic at all</b>. Line width = how much the phones saw there.</div>`;
  else if(S.colorBy === "syn")
    el.innerHTML = bar(rampColor, "few", "", "busiest", "Model scale") +
      `<div class="cap"><b>Synthetic car trips per day</b>, averaged along the corridor (2019 residents only).</div>`;
  else
    el.innerHTML = bar(framp, "few", "", "busiest", "Phone scale") +
      `<div class="cap"><b>Sampled phone crossings</b> (≥ 20 km/h), averaged along the corridor. A 100,000-crossing
      sample of 2024 traffic, so this is a relative index, never vehicles per day.</div>`;
}

export function showNote(el){
  if(!el || !D) return;
  const n = D.corridors.filter(well).length;
  el.innerHTML = S.onlyWell
    ? `Showing the <b>${n}</b> corridors with at least ${minCross()} sampled crossings and 400 m of length.
       The other ${fmtN(D.corridors.length - n)} are faint: too little phone data to rank.`
    : `Showing all <b>${fmtN(D.corridors.length)}</b> corridors. Those under ${minCross()} crossings are faint —
       the phones saw too little there to rank them.`;
}

export function agreement(el){
  if(!el || !D || !D.stats) return;
  const c = D.stats.corridor_level, s = D.stats.segment_level_for_reference || {};
  const cell = v => v && v.spearman != null
    ? `<td class="${Math.abs(v.spearman) >= 0.5 ? "good" : "bad"}">${v.spearman.toFixed(2)}</td>` : "<td>–</td>";
  const row = (label, k) => `<tr><td>${label}</td>${cell(c[k])}${cell(s[k])}</tr>`;
  el.innerHTML = `<table class="rho">
    <tr><th></th><th>corridor</th><th>segment</th></tr>
    ${row("model vs phones", "synthetic_vs_phone20")}
    ${row("model vs counts", "synthetic_vs_counts")}
    ${row("phones vs counts", "phone20_vs_counts")}</table>
    <div class="cap">Spearman rank correlation. Aggregating segments into corridors does <b>not</b> bring the
    model closer to the phones; the phones stay close to the real 2023 counts either way.</div>`;
}

// the busiest corridors, as clickable rows
export function list(el, onPick){
  if(!el || !D) return;
  const top = D.corridors.filter(well).slice(0, 15);
  el.innerHTML = top.map(c => {
    const i = D.corridors.indexOf(c), col = diverge(Math.max(-1, Math.min(1, (c.ratio||0)/RATIO_MAX)));
    const tag = c.syn === 0 ? "none" : (c.ratio > 0 ? "+" : "") + c.ratio.toFixed(1);
    return `<button class="row" data-i="${i}" aria-pressed="${i === S.selected}"
      title="${c.syn === 0 ? "no synthetic traffic at all" : "log2 of the two shares"}">
      <span class="sw" style="background:rgb(${col.map(Math.round).join(",")})"></span>
      <span>${c.name}</span><span class="v">${tag}</span></button>`;
  }).join("");
  el.onclick = e => {
    const b = e.target.closest("[data-i]");
    if(b) onPick(+b.dataset.i);
  };
}

// ---------- the bottom bar ----------
export function detail(nameEl, subEl, figEl){
  const c = corridor(S.selected);
  if(!c){
    const st = D.stats.corridor_level, n = D.corridors.filter(well).length;
    nameEl.textContent = "Pick a corridor";
    subEl.textContent = "Click one on the map, or in the list on the right.";
    figEl.innerHTML = [
      ["corridors compared", fmtN(D.corridors.length), ""],
      ["well observed", fmtN(n), ""],
      ["model vs phones", (st.synthetic_vs_phone20.spearman ?? 0).toFixed(2), "ρ"],
      ["phones vs counts", (st.phone20_vs_counts.spearman ?? 0).toFixed(2), "ρ"],
    ].map(([k, v, u]) => `<div class="fig"><div class="k">${k}</div><div class="n">${v}<small>${u}</small></div></div>`).join("");
    return;
  }
  nameEl.textContent = c.name;
  subEl.textContent = `${c.km} km · ${fmtN(c.cross)} sampled crossings` +
    (c.nc ? ` · ${c.nc} count site${c.nc > 1 ? "s" : ""}` : " · no count site");
  const verdict = c.syn === 0 ? "the model has no traffic here at all"
    : c.ratio >= 1 ? `the model puts ${(2**c.ratio).toFixed(1)}× more traffic here than the phones`
    : c.ratio <= -1 ? `the model puts ${(2**-c.ratio).toFixed(1)}× less traffic here than the phones`
    : "the two agree here";
  figEl.innerHTML = [
    ["model", fmtN(c.syn), "cars/day"],
    ["phones", (c.ph20 ?? 0).toFixed(1), "crossings"],
    ["share of city", `${(c.synS ?? 0).toFixed(1)} / ${(c.ph20S ?? 0).toFixed(1)}`, "‰ model/phone"],
    ["2023 counts", c.adt == null ? "–" : fmtN(c.adt), c.adt == null ? "" : "veh/day"],
  ].map(([k, v, u]) => `<div class="fig"><div class="k">${k}</div><div class="n">${v}<small>${u}</small></div></div>`).join("")
    + `<div class="fig" style="min-width:150px"><div class="k">reading</div><div class="n" style="font-size:12px;line-height:1.5">${verdict}</div></div>`;
}

export function tooltip(info){
  const i = pick(info);
  if(i >= 0){
    const c = D.corridors[i];
    return {style:tipStyle, html:`<div style="font-weight:500">${c.name}</div>
      <div style="color:#8195A8;font-size:10px;letter-spacing:.08em">${c.km} KM · ${fmtN(c.cross)} SAMPLED CROSSINGS</div>
      <div style="margin-top:5px">model <b>${fmtN(c.syn)}</b> cars/day · ${(c.synS ?? 0).toFixed(1)}‰ of the city</div>
      <div>phones <b>${(c.ph20 ?? 0).toFixed(1)}</b> crossings · ${(c.ph20S ?? 0).toFixed(1)}‰ of the city</div>
      ${c.adt != null ? `<div>2023 counts <b>${fmtN(c.adt)}</b> vehicles/day</div>` : ""}
      <div style="margin-top:5px;color:#8195A8">${c.syn === 0 ? "no synthetic traffic at all"
        : `log2 share ratio ${c.ratio > 0 ? "+" : ""}${c.ratio.toFixed(2)}`}</div>`};
  }
  if(info && info.layer && info.layer.id === "counts" && info.object){
    const d = info.object;
    return {style:tipStyle, html:`<div style="font-weight:500">${d.name || "Trafikverket link"}</div>
      <div style="color:#8195A8;font-size:10px;letter-spacing:.08em">${d.src === "highway" ? "TRAFIKVERKET" : "GÖTEBORG STAD"} COUNT · 2023</div>
      <div style="font-size:18px;margin:4px 0">${fmtN(d.adt)} <span style="font-size:11px;color:#8195A8">vehicles / day</span></div>`};
  }
  return null;
}
