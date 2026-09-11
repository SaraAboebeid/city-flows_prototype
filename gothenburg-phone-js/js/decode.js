// Decoders for the payload formats written by the pipeline.

export function b64(s){
  const bin = atob(s), out = new Uint8Array(bin.length);
  for(let i=0;i<bin.length;i++) out[i]=bin.charCodeAt(i);
  return out;
}

// base64 of gzip -> ArrayBuffer (native DecompressionStream)
export async function inflate(s){
  const stream = new Blob([b64(s)]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).arrayBuffer();
}

// polylines: int32 first vertex + int16 deltas, 1e-5 degrees
export function lines(buf, npts){
  const n = npts.length; let total = 0;
  for(let i=0;i<n;i++) total += npts[i];
  const pos = new Float32Array(total*2), start = new Uint32Array(n+1), dv = new DataView(buf);
  let o = 0, w = 0;
  for(let i=0;i<n;i++){
    start[i] = w;
    let x = dv.getInt32(o,true); o+=4; let y = dv.getInt32(o,true); o+=4;
    pos[w*2]=x/1e5; pos[w*2+1]=y/1e5; w++;
    for(let k=1;k<npts[i];k++){
      x += dv.getInt16(o,true); o+=2; y += dv.getInt16(o,true); o+=2;
      pos[w*2]=x/1e5; pos[w*2+1]=y/1e5; w++;
    }
  }
  start[n] = w;
  return {pos, start};
}

// A trip sample (meta: F int32 per trip, t0 t1 mode npts ...). Per-vertex
// timestamps come from cumulative distance between the trip's start and end.
export function decodeSample(m, buf, n, F){
  const dv = new DataView(buf);
  let tot = 0;
  for(let i=0;i<n;i++) tot += m[i*F+3];
  const pos = new Float32Array(tot*2), ts = new Float32Array(tot), off = new Uint32Array(n+1);
  let o = 0, w = 0, tMin = Infinity, tMax = -Infinity;
  for(let i=0;i<n;i++){
    const t0 = m[i*F], t1 = m[i*F+1], np = m[i*F+3];
    off[i] = w;
    let x = dv.getInt32(o,true); o+=4; let y = dv.getInt32(o,true); o+=4;
    const xs = new Float64Array(np), ys = new Float64Array(np);
    xs[0]=x; ys[0]=y;
    for(let k=1;k<np;k++){ x += dv.getInt16(o,true); o+=2; y += dv.getInt16(o,true); o+=2; xs[k]=x; ys[k]=y; }
    let cum = 0; const d = new Float64Array(np);
    for(let k=1;k<np;k++){ cum += Math.hypot(xs[k]-xs[k-1], ys[k]-ys[k-1]); d[k]=cum; }
    const span = Math.max(1, t1-t0);
    for(let k=0;k<np;k++){
      pos[(w+k)*2] = xs[k]/1e5; pos[(w+k)*2+1] = ys[k]/1e5;
      ts[w+k] = t0 + (cum>0 ? d[k]/cum : (np>1 ? k/(np-1) : 0))*span;
    }
    w += np;
    if(t0<tMin) tMin=t0;
    if(t1>tMax) tMax=t1;
  }
  off[n] = w;
  return {meta:m, F, n, pos, ts, off, tMin, tMax};
}

export function pctile(arr, q){
  const a = Float64Array.from(arr).filter(v=>v>0).sort();
  return a.length ? a[Math.min(a.length-1, Math.floor(q*(a.length-1)))] : 1;
}
