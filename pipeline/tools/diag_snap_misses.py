"""Where do route samples fail to snap to a street?

Splits samples by position in the trip (first/last route segment vs interior),
by distance to the nearest street, and by segment length, for a few thousand
street-routed trips.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DER  # noqa: E402

import numpy as np
import pyarrow.parquet as pq
from pyproj import Transformer
from scipy.spatial import cKDTree

tf = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)

st = pq.read_table(os.path.join(DER, "streets.parquet"), columns=["lon", "lat"])
lo = st.column("lon").combine_chunks(); la = st.column("lat").combine_chunks()
off = np.asarray(lo.offsets)
X, Y = tf.transform(np.asarray(lo.values), np.asarray(la.values))
own = np.repeat(np.arange(len(off) - 1), np.diff(off))
same = own[1:] == own[:-1]
i0 = np.flatnonzero(same)
pts = []
for a in i0[::1]:
    pass
dx, dy = X[i0 + 1] - X[i0], Y[i0 + 1] - Y[i0]
L = np.hypot(dx, dy)
ns = np.maximum(1, np.ceil(L / 2).astype(int)) + 1
r = np.repeat(np.arange(len(i0)), ns)
k = np.arange(len(r)) - np.repeat(np.cumsum(ns) - ns, ns)
f = k / (ns[r] - 1)
tree = cKDTree(np.column_stack([X[i0][r] + f * dx[r], Y[i0][r] + f * dy[r]]))
node_tree = cKDTree(np.column_stack([X, Y]))

pf = pq.ParquetFile(os.path.join(DER, "trips_final2.parquet"))
b = next(pf.iter_batches(batch_size=30000, columns=["lon", "lat", "match", "mode", "n_pts"]))
tl = b.to_pydict()
S_pos, S_len, S_d, S_mode, V_d = [], [], [], [], []
used = 0
for lon, lat, m, md in zip(tl["lon"], tl["lat"], tl["match"], tl["mode"]):
    if m != "n/a" or len(lon) < 3:
        continue
    x, y = tf.transform(np.asarray(lon), np.asarray(lat))
    V_d.append(node_tree.query(np.column_stack([x, y]))[0])
    segL = np.hypot(np.diff(x), np.diff(y))
    nseg = len(segL)
    for j in range(nseg):
        n = max(1, int(np.ceil(segL[j] / 10)))
        for q in range(n):
            t = (q + 0.5) / n
            S_pos.append(0 if j == 0 else (2 if j == nseg - 1 else 1))
            S_len.append(segL[j])
            S_mode.append(md)
            S_d.append((x[j] + t * (x[j+1] - x[j]), y[j] + t * (y[j+1] - y[j])))
    used += 1
    if used >= 3000:
        break

P = np.asarray(S_d); pos = np.asarray(S_pos); sl = np.asarray(S_len)
d, _ = tree.query(P)
vd = np.concatenate(V_d)
print(f"{used} trips, {len(P):,} samples, {len(vd):,} vertices")
print(f"vertices within 0.5 m of an OSM node: {100*(vd <= .5).mean():.1f}%")
print(f"samples within 4 m of a street: {100*(d <= 4).mean():.1f}%\n")
for lab, msk in (("first segment", pos == 0), ("interior", pos == 1),
                 ("last segment", pos == 2)):
    print(f"  {lab:14s} share of samples {100*msk.mean():5.1f}%  "
          f"snapped {100*(d[msk] <= 4).mean():5.1f}%")
print("\nmissed samples by distance to nearest street:")
miss = d > 4
for lo_, hi_ in ((4, 10), (10, 25), (25, 50), (50, 1e9)):
    k_ = miss & (d > lo_) & (d <= hi_)
    print(f"  {lo_:>3}-{hi_ if hi_ < 1e9 else 'inf':>4} m: {100*k_.sum()/len(d):5.1f}% of all samples")
print("\nsnap rate by route-segment length:")
for lo_, hi_ in ((0, 20), (20, 50), (50, 100), (100, 300), (300, 1e9)):
    k_ = (sl > lo_) & (sl <= hi_)
    print(f"  {lo_:>4}-{hi_ if hi_ < 1e9 else 'inf':>4} m segments: {100*k_.mean():5.1f}% of samples, "
          f"snapped {100*(d[k_] <= 4).mean():5.1f}%")
