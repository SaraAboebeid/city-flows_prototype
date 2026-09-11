// The animation sample: filtering, grouping into TripsLayer data, counts.
import { S } from "./state.js";

export let layerData = [];
export let activeIdx = [];
let seriesCache = null;

// Trip duration in the source is sampled independently of the route, so
// implied speeds are meaningless. Distance is real, so the filter caps
// distance per mode - it removes 33.6% of walking trips and little else.
export function passesDemo(i){
  const { meta, M, filt } = S;
  if(S.plausOnly && meta[i*M+8] !== 1) return false;
  for(const k in filt){
    const f = filt[k];
    if(!f.sel.has(f.names[meta[i*M+f.slot]])) return false;
  }
  return true;
}

export function rebuild(){
  const { meta, M, N, off, POS, TS, on, dim } = S;
  const D = S.DIMS[dim];
  const groups = new Map();
  activeIdx = [];
  for(let i=0;i<N;i++){
    if(!passesDemo(i)) continue;
    const name = D.names[meta[i*M+D.slot]];
    if(!on[dim].has(name)) { activeIdx.push(i); continue; }
    let g = groups.get(name);
    if(!g){ g = {ids:[], verts:0}; groups.set(name, g); }
    g.ids.push(i); g.verts += meta[i*M+3];
    activeIdx.push(i);
  }
  layerData = [];
  for(const [name,g] of groups){
    const pos = new Float32Array(g.verts*2);
    const ts  = new Float32Array(g.verts);
    const si  = new Uint32Array(g.ids.length+1);
    let p = 0;
    for(let j=0;j<g.ids.length;j++){
      const i = g.ids[j], s = off[i], n = off[i+1]-off[i];
      si[j] = p;
      pos.set(POS.subarray(s*2,(s+n)*2), p*2);
      ts.set(TS.subarray(s,s+n), p);
      p += n;
    }
    si[g.ids.length] = p;
    layerData.push({
      name,
      color: D.colors[name] || [200,200,200],
      data:{length:g.ids.length, startIndices:si,
            attributes:{getPath:{value:pos,size:2},
                        getTimestamps:{value:ts,size:1}}}
    });
  }
  seriesCache = null;
}

export function countActive(){
  const { meta, M, on, dim, current } = S;
  const D = S.DIMS[dim];
  let n=0;
  for(const i of activeIdx){
    if(!on[dim].has(D.names[meta[i*M+D.slot]])) continue;
    if(meta[i*M]<=current && meta[i*M+1]>=current) n++;
  }
  return n;
}

// stacked "trips under way" for the chart
export const NB = 96;
export function series(){
  if(seriesCache) return seriesCache;
  const { meta, M, on, dim, T0, T1 } = S;
  const D = S.DIMS[dim];
  const names = D.names.filter(n=>on[dim].has(n));
  const arr = names.map(()=>new Float64Array(NB));
  const pos = new Map(names.map((n,k)=>[n,k]));
  for(const i of activeIdx){
    const nm = D.names[meta[i*M+D.slot]];
    const k = pos.get(nm);
    if(k===undefined) continue;
    const a = Math.floor((meta[i*M]-T0)/(T1-T0)*NB);
    const b = Math.floor((meta[i*M+1]-T0)/(T1-T0)*NB);
    for(let x=Math.max(0,a); x<=Math.min(NB-1,b); x++) arr[k][x]++;
  }
  const tot = new Float64Array(NB);
  arr.forEach(a=>{ for(let x=0;x<NB;x++) tot[x]+=a[x]; });
  seriesCache = {names, arr, max:Math.max(1,...tot)};
  return seriesCache;
}
