// STREET FLOWS: trips projected onto OSM street segments (grey width =
// volume) with trips re-traced along the streets moving on top, coloured by
// mode or purpose. Unpacked after the animation starts.
import { S, TRAIL } from "./state.js";
import { inflate, lines, decodeSample, pctile } from "./decode.js";
import { MODE_COLORS, nramp, diverge } from "./colors.js";

let FP = null, FSP = null;
let FS = null, flowTripData = [];
export let flows = null;
export let flowStreets = 0;
export let flowLastBin = -1;
let flowVersion = 0, flowLens = null;
const FMINW = 0.5, FMAXW = 9, SHARE_MIN_DAY = 50;

export function initFlows(fp, fsp){ FP = fp; FSP = fsp; }

export async function loadFlows(){
  if(typeof DecompressionStream === "undefined" || !FP || !FP.street) return;
  const Sx = FP.street, T = FP.transit;
  const bufs = await Promise.all([Sx.coords,Sx.npts,Sx.bymode,Sx.shares,Sx.hw,Sx.name,
    Sx.row_start,Sx.key,Sx.val,T.coords,T.npts,T.grp,T.day,T.row_start,T.bin,T.val].map(inflate));
  const NSM = FP.street_modes.length;
  const f = {
    NSM, NSH:FP.share_names.length, nb:FP.nbin,
    street:{n:Sx.n, ...lines(bufs[0], new Uint16Array(bufs[1])),
      bymode:new Uint32Array(bufs[2]), shares:new Uint8Array(bufs[3]),
      hw:new Uint8Array(bufs[4]), name:new Uint32Array(bufs[5]),
      rowStart:new Uint32Array(bufs[6]), key:new Uint16Array(bufs[7]), val:new Uint16Array(bufs[8])},
    transit:{n:T.n, ...lines(bufs[9], new Uint16Array(bufs[10])),
      grp:new Uint8Array(bufs[11]), day:new Uint32Array(bufs[12]),
      rowStart:new Uint32Array(bufs[13]), bin:new Uint8Array(bufs[14]), val:new Uint16Array(bufs[15])}
  };
  const s = f.street;
  f.dayTot = new Float64Array(s.n);
  for(let i=0;i<s.n;i++){ let v=0; for(let m=0;m<NSM;m++) v+=s.bymode[i*NSM+m]; f.dayTot[i]=v; }
  const binVols = [];
  for(let i=0;i<s.n;i++){
    let last=-1, acc=0;
    for(let r=s.rowStart[i]; r<s.rowStart[i+1]; r++){
      const b = (s.key[r]/NSM)|0;
      if(b!==last){ if(last>=0) binVols.push(acc); last=b; acc=0; }
      acc += s.val[r];
    }
    if(last>=0) binVols.push(acc);
  }
  f.ref = {day:pctile(f.dayTot,0.995), bin:pctile(binVols,0.995),
           tday:pctile(f.transit.day,0.995), tbin:pctile(f.transit.val,0.995)};
  f.sVol = new Float32Array(s.n); f.sCol = new Uint8Array(s.n*4); f.sWid = new Float32Array(s.n);
  f.tVol = new Float32Array(f.transit.n); f.tCol = new Uint8Array(f.transit.n*4);
  f.tWid = new Float32Array(f.transit.n);
  if(FSP && FSP.n){
    const [mbuf, cbuf] = await Promise.all([inflate(FSP.meta), inflate(FSP.coords)]);
    FS = decodeSample(new Int32Array(mbuf), cbuf, FSP.n, FSP.fields);
  }
  flows = f;
  rebuildFlowTrips();
}

// group the re-traced trips by the current colour dimension, honouring the
// same controls as the animation (mode/purpose list, age, sex, activity)
export function rebuildFlowTrips(){
  flowTripData = [];
  if(!FS) return;
  const { dim, on, filt } = S;
  const D = S.DIMS[dim], m = FS.meta, F = FS.F, groups = new Map();
  for(let i=0;i<FS.n;i++){
    const o = i*F;
    if(S.plausOnly && m[o+8] !== 1) continue;
    let ok = true;
    for(const k in filt){ const f = filt[k]; if(!f.sel.has(f.names[m[o+f.slot]])){ ok = false; break; } }
    if(!ok) continue;
    const name = D.names[m[o+D.slot]];
    if(!on[dim].has(name)) continue;
    let g = groups.get(name);
    if(!g){ g = {ids:[], v:0}; groups.set(name, g); }
    g.ids.push(i); g.v += FS.off[i+1]-FS.off[i];
  }
  for(const [name, g] of groups){
    const pos = new Float32Array(g.v*2), ts = new Float32Array(g.v), si = new Uint32Array(g.ids.length+1);
    let p = 0;
    g.ids.forEach((i,j)=>{
      const s = FS.off[i], n = FS.off[i+1]-s;
      si[j] = p; pos.set(FS.pos.subarray(s*2,(s+n)*2), p*2); ts.set(FS.ts.subarray(s,s+n), p); p += n;
    });
    si[g.ids.length] = p;
    flowTripData.push({name, color:D.colors[name]||[200,200,200],
      data:{length:g.ids.length, startIndices:si,
            attributes:{getPath:{value:pos,size:2}, getTimestamps:{value:ts,size:1}}}});
  }
}

export function flowBin(){
  return Math.max(0, Math.min(FP.nbin-1,
    Math.floor((S.current - FP.hour0*3600)/(FP.bin_min*60))));
}

// The panel's controls drive the flows: the MODE list switches modes on and
// off, and narrowing to exactly one group (one purpose, age band, sex or
// activity) switches the streets to that group's share of their trips.
function flowShareTarget(){
  const { dim, on, filt } = S;
  const picks = [];
  if(dim === "purpose" && on.purpose.size === 1) picks.push(["purpose", [...on.purpose][0]]);
  for(const k of ["age","sex","status"])
    if(filt[k].sel.size === 1) picks.push([k, [...filt[k].sel][0]]);
  if(picks.length !== 1) return null;
  const [d, v] = picks[0], g = FP.share_names.indexOf(d+":"+v);
  return g < 0 ? null : {dim:d, value:v, g, city:FP.city_share[d+":"+v]};
}

export function computeFlows(){
  if(!flows) return;
  const f = flows, s = f.street, t = f.transit, NSM = f.NSM;
  const modeOn = m => S.dim !== "mode" || S.on.mode.has(m);
  const sOn = FP.street_modes.map(modeOn), tOn = FP.tgroups.map(modeOn);
  const b = flowBin(), whole = S.flowsWholeDay;
  flowLastBin = b;
  let active = 0;
  for(let i=0;i<s.n;i++){
    let v = 0;
    if(whole){ for(let m=0;m<NSM;m++) if(sOn[m]) v += s.bymode[i*NSM+m]; }
    else for(let r=s.rowStart[i]; r<s.rowStart[i+1]; r++){
      const k = s.key[r], kb = (k/NSM)|0;
      if(kb===b && sOn[k%NSM]) v += s.val[r];
      else if(kb>b) break;
    }
    f.sVol[i] = v;
    if(v>0) active++;
  }
  flowStreets = active;
  flowLens = flowShareTarget();
  if(flowLens){
    for(let i=0;i<s.n;i++){
      const v = f.dayTot[i];
      if(v < SHARE_MIN_DAY){ f.sWid[i]=0; f.sCol[i*4+3]=0; continue; }
      const sh = s.shares[i*f.NSH+flowLens.g]/255;
      const c = diverge(Math.max(-1, Math.min(1,
        Math.log2(Math.max(sh,1e-3)/Math.max(flowLens.city,1e-6))/1.3)));
      f.sCol.set([c[0],c[1],c[2],230], i*4);
      f.sWid[i] = 0.7 + 5.5*Math.sqrt(Math.min(1, v/f.ref.day));
    }
    f.tWid.fill(0);
  } else {
    // volumes are a quiet neutral backdrop (width + brightness); colour is
    // carried by the moving trips drawn on top
    const ref = whole ? f.ref.day : f.ref.bin;
    for(let i=0;i<s.n;i++){
      const v = f.sVol[i];
      if(v<=0){ f.sWid[i]=0; f.sCol[i*4+3]=0; continue; }
      const q = Math.sqrt(Math.min(1, v/ref)), c = nramp(q);
      f.sCol.set([c[0],c[1],c[2],80+Math.round(120*q)], i*4);
      f.sWid[i] = FMINW + (FMAXW-FMINW)*q;
    }
    for(let p=0;p<t.n;p++){
      let v = 0;
      if(tOn[t.grp[p]]){
        if(whole) v = t.day[p];
        else for(let r=t.rowStart[p]; r<t.rowStart[p+1]; r++) if(t.bin[r]===b){ v = t.val[r]; break; }
      }
      f.tVol[p] = v;
      if(v<=0){ f.tWid[p]=0; f.tCol[p*4+3]=0; continue; }
      const q = Math.sqrt(Math.min(1, v/(whole ? f.ref.tday : f.ref.tbin)));
      const c = nramp(q);
      f.tCol.set([c[0],c[1],c[2],60+Math.round(110*q)], p*4);
      f.tWid[p] = 0.8 + 5*q;
    }
  }
  flowVersion++;
  renderFlowLegend();
}

export function flowLayers(){
  const f = flows, s = f.street, t = f.transit, Dash = deck.PathStyleExtension;
  const out = [new deck.PathLayer({
    id:"streets", data:{length:s.n, startIndices:s.start,
      attributes:{getPath:{value:s.pos, size:2}}}, _pathType:"open",
    getColor:(_, {index}) => [f.sCol[index*4], f.sCol[index*4+1], f.sCol[index*4+2], f.sCol[index*4+3]],
    getWidth:(_, {index}) => f.sWid[index],
    widthUnits:"pixels", widthMinPixels:0, capRounded:true, jointRounded:true,
    pickable:true, autoHighlight:true, highlightColor:[255,255,255,90],
    updateTriggers:{getColor:flowVersion, getWidth:flowVersion}, parameters:{depthTest:false}
  })];
  if(!flowLens) out.push(new deck.PathLayer({
    id:"transit", data:{length:t.n, startIndices:t.start,
      attributes:{getPath:{value:t.pos, size:2}}}, _pathType:"open",
    getColor:(_, {index}) => [f.tCol[index*4], f.tCol[index*4+1], f.tCol[index*4+2], f.tCol[index*4+3]],
    getWidth:(_, {index}) => f.tWid[index],
    widthUnits:"pixels", widthMinPixels:0, pickable:true, autoHighlight:true,
    highlightColor:[255,255,255,90],
    updateTriggers:{getColor:flowVersion, getWidth:flowVersion},
    ...(Dash ? {extensions:[new Dash({dash:true})], getDashArray:[3,2], dashJustified:true} : {}),
    parameters:{depthTest:false}
  }));
  // the movement: re-traced trips flowing along the streets, coloured by
  // mode or purpose (hidden in the share lens, which is a whole-day view)
  if(!flowLens) flowTripData.forEach(L => out.push(new deck.TripsLayer({
    id:"flowtrips-"+L.name, data:L.data, getColor:L.color, opacity:0.92,
    widthMinPixels:2, jointRounded:true, capRounded:true,
    trailLength:TRAIL, currentTime:S.current, parameters:{depthTest:false}
  })));
  return out;
}

const fmtN = n => Math.round(n).toLocaleString("en");
const compactN = n => n>=1e4 ? Math.round(n/1e3)+"k" : n>=1e3 ? (n/1e3).toFixed(1)+"k" : String(Math.round(n));
function flowBinLabel(b){
  const s = FP.hour0*3600 + b*FP.bin_min*60, e = s + FP.bin_min*60;
  const c = t => String(Math.floor(t/3600)%24).padStart(2,"0")+":"+String(Math.floor(t%3600/60)).padStart(2,"0");
  return c(s)+"–"+c(e);
}

function renderFlowLegend(){
  const el = document.getElementById("flowLegend");
  if(!flows || !S.showFlows){ return; }
  const st = FP.stats;
  const caveat = `Projected onto OpenStreetMap segments (${st.snap_pct}% of route length matched). `+
    `The Torslanda corridor dominates because the source sends ~29% of all work trips to the Volvo Cars site.`;
  if(flowLens){
    let bars = "";
    for(let k=0;k<40;k++){ const c = diverge(-1+2*k/39).map(Math.round);
      bars += `<rect x="${k*5.5}" y="4" width="5.7" height="11" fill="rgb(${c.join(",")})"/>`; }
    const lab = x => `${Math.round(100*Math.min(1, flowLens.city*x))}%`;
    el.innerHTML = `<svg viewBox="0 0 220 34" role="img" aria-label="Share scale">${bars}
      <text x="0" y="30" fill="#8195A8" font-size="10" font-family="IBM Plex Mono, monospace">${lab(2**-1.3)}</text>
      <text x="110" y="30" fill="#DCE6F0" font-size="10" text-anchor="middle" font-family="IBM Plex Mono, monospace">${lab(1)} city</text>
      <text x="220" y="30" fill="#8195A8" font-size="10" text-anchor="end" font-family="IBM Plex Mono, monospace">${lab(2**1.3)}+</text></svg>
      <div class="cap">Share of each street's trips made by <b>${flowLens.value}</b> — whole day, all street modes, streets with ≥ ${SHARE_MIN_DAY} trips/day. Violet = under, ember = over the city average.</div>
      <div class="cap">${caveat}</div>`;
    return;
  }
  const ref = S.flowsWholeDay ? flows.ref.day : flows.ref.bin;
  let svg = "";
  [0.02,0.15,0.45,1].forEach((q,k)=>{
    const v = ref*q, f = Math.sqrt(q), c = nramp(f).map(Math.round), w = FMINW+(FMAXW-FMINW)*f, x = 6+k*54;
    svg += `<line x1="${x}" y1="10" x2="${x+38}" y2="10" stroke="rgb(${c.join(",")})" stroke-width="${w}" stroke-linecap="round"/>
      <text x="${x+19}" y="31" fill="#8195A8" font-size="10" text-anchor="middle" font-family="IBM Plex Mono, monospace">${compactN(v)}</text>`;
  });
  const moving = FS ? `<b>Moving trails</b> are ${fmtN(FS.n)} trips re-traced along these streets, coloured by ${S.dim} — `+
    `use the list above to switch modes or purposes on and off. ` : "";
  el.innerHTML = `<svg viewBox="0 0 222 36" role="img" aria-label="Volume scale">${svg}</svg>
    <div class="cap"><b>Grey width</b> = trips per street segment, ${S.flowsWholeDay ? "whole day" : flowBinLabel(flowLastBin)}. `+
    `${moving}Pick one age, sex, activity or purpose to see its share instead. Dashed = inferred tram, bus, ferry.`+
    `${S.flowsWholeDay ? "" : ` 15-min widths cover the ${fmtN(st.cube_segments)} busiest segments.`}</div>
    <div class="cap">${caveat}</div>`;
}

const tipStyle = {background:"rgba(14,23,32,.96)", color:"#DCE6F0",
  border:"1px solid #1D2C39", borderRadius:"3px", padding:"10px 12px",
  fontFamily:"'IBM Plex Mono', monospace", fontSize:"11.5px", lineHeight:"1.5"};

export function flowTooltip({layer, index}){
  if(!S.showFlows || !flows || !layer || index < 0) return null;
  const f = flows, unit = S.flowsWholeDay ? "trips / day" : "trips, "+flowBinLabel(flowLastBin);
  if(layer.id === "streets"){
    const s = f.street, name = FP.name_vocab[s.name[index]] || "Unnamed street";
    const rows = FP.street_modes.map((m,k)=>
      `<div style="display:flex;justify-content:space-between;gap:14px"><span><i style="display:inline-block;width:8px;height:8px;border-radius:2px;background:rgb(${MODE_COLORS[m].join(",")});margin-right:6px"></i>${m}</span><span>${fmtN(s.bymode[index*f.NSM+k])}</span></div>`).join("");
    const head = flowLens
      ? `${(100*s.shares[index*f.NSH+flowLens.g]/255).toFixed(0)}% <span style="font-size:11px;color:#8195A8">${flowLens.value} · city ${(100*flowLens.city).toFixed(0)}%</span>`
      : `${fmtN(f.sVol[index])} <span style="font-size:11px;color:#8195A8">${unit}</span>`;
    return {style:tipStyle, html:`<div style="font-weight:500">${name}</div>
      <div style="color:#8195A8;font-size:10px;letter-spacing:.08em;text-transform:uppercase">${FP.hw_vocab[s.hw[index]]}</div>
      <div style="font-size:18px;margin:4px 0">${head}</div>
      <div style="color:#55697C;font-size:10px;margin:6px 0 3px;letter-spacing:.1em">WHOLE DAY BY MODE</div>${rows}`};
  }
  if(layer.id === "transit"){
    const t = f.transit;
    return {style:tipStyle, html:`<div style="font-weight:500">${FP.tgroups[t.grp[index]]} <span style="font-size:9px;border:1px solid #55697C;padding:0 3px;border-radius:2px;color:#8195A8">INFERRED</span></div>
      <div style="font-size:18px;margin:4px 0">${fmtN(f.tVol[index])} <span style="font-size:11px;color:#8195A8">${unit}</span></div>
      <div style="color:#8195A8;font-size:10.5px;max-width:220px">Shortest path over OSM transit lines, not a recorded service.</div>`};
  }
  return null;
}
