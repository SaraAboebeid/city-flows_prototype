// STREET LOAD: 100 m grid of trips present per 15 minutes.
import { S } from "./state.js";
import { b64 } from "./decode.js";
import { rampColor } from "./colors.js";

export let loadCells = null;

export function initLoad(LOAD){
  if(!LOAD || !LOAD.ncell) return;
  const pb = b64(LOAD.pos);
  const pos32 = new Int32Array(pb.buffer, pb.byteOffset, LOAD.ncell*2);
  const cbb = b64(LOAD.counts);
  const cnt = new Uint8Array(cbb.buffer, cbb.byteOffset, LOAD.nbin*LOAD.ncell);
  loadCells = {pos:pos32, cnt, nbin:LOAD.nbin, ncell:LOAD.ncell,
               hour0:LOAD.hour0, peak:LOAD.peak,
               binS:(LOAD.bin_min || 60) * 60,
               radius:(LOAD.cell_m || 200) * 0.66};
}

// rows are identical for every frame within a bin, so build once per bin
const loadRowCache = new Map();
function loadRows(bin){
  let rows = loadRowCache.get(bin);
  if(rows) return rows;
  const base = bin*loadCells.ncell;
  rows = [];
  for(let c=0;c<loadCells.ncell;c++){
    const u = loadCells.cnt[base+c];
    if(!u) continue;
    // counts are sqrt-scaled to uint8; saturate the ramp at ~36% of peak
    const col = rampColor(Math.min(1, (u/255)/0.6));
    rows.push({p:[loadCells.pos[c*2]/1e5, loadCells.pos[c*2+1]/1e5],
               c:[col[0],col[1],col[2],190]});
  }
  loadRowCache.set(bin, rows);
  return rows;
}

export function loadLayer(){
  if(!S.showLoad || !loadCells) return null;
  let bin = Math.floor((S.current - loadCells.hour0*3600)/loadCells.binS);
  bin = Math.max(0, Math.min(loadCells.nbin-1, bin));
  return new deck.ScatterplotLayer({
    id:"load", data:loadRows(bin), getPosition:d=>d.p,
    radiusUnits:"meters", getRadius:loadCells.radius, stroked:false,
    radiusMinPixels:0.8,
    getFillColor:d=>d.c,
    updateTriggers:{getFillColor:[bin], getPosition:[bin]},
    parameters:{depthTest:false}
  });
}
