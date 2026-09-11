"""Where do trips end? Is the Torslanda flow a real concentration of
destinations in the synthetic population?"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DER  # noqa: E402
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from pyproj import Transformer

tf = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)
t = pq.read_table(os.path.join(DER, "trips_final2.parquet"),
                  columns=["lon", "lat", "mode", "purpose_to", "purpose_from",
                           "plausible", "neighborhood"])
lon, lat = t.column("lon").combine_chunks(), t.column("lat").combine_chunks()
off = np.asarray(lon.offsets); fl = np.asarray(lon.values); fa = np.asarray(lat.values)
dx, dy = tf.transform(fl[off[1:] - 1], fa[off[1:] - 1])       # destinations
ox, oy = tf.transform(fl[off[:-1]], fa[off[:-1]])             # origins
df = t.select(["mode", "purpose_to", "purpose_from", "plausible", "neighborhood"]).to_pandas()
N = len(df)

# 250 m destination grid: where do most trips end?
cell = 250
key = (np.floor(dx / cell).astype(np.int64) << 32) + np.floor(dy / cell).astype(np.int64)
u, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
order = np.argsort(-cnt)[:12]
to4326 = Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)
print("busiest 250 m destination cells:")
for k in order:
    cx = ((u[k] >> 32) + 0.5) * cell; cy = ((u[k] & 0xffffffff) + 0.5) * cell
    lo, la = to4326.transform(cx, cy)
    sel = inv == k
    top_p = df.purpose_to[sel].value_counts().head(3)
    exact = len(np.unique(np.round(dx[sel]) * 1e7 + np.round(dy[sel])))
    print(f"  {lo:.4f},{la:.4f}  {cnt[k]:>7,} trips ({100*cnt[k]/N:.1f}%)  "
          f"distinct end points {exact:>5,}  | " +
          ", ".join(f"{p} {v:,}" for p, v in top_p.items()))

# Torslanda / Volvo area box
box = (dx > 312500) & (dx < 316500) & (dy > 6400600) & (dy < 6403800)
print(f"\ntrips ENDING in the Torslanda/Volvo box: {box.sum():,} ({100*box.mean():.1f}%)")
print(df.purpose_to[box].value_counts().head(5).to_string())
print(df["mode"][box].value_counts().head(4).to_string())
print("\nhome neighbourhoods of those trips (top 8):")
print(df.neighborhood[box].value_counts().head(8).to_string())
print("\nexact end points in that box: top 5 coordinates by trip count")
pts = pd.Series(list(zip(np.round(dx[box]), np.round(dy[box])))).value_counts().head(5)
for (x, y), c in pts.items():
    lo, la = to4326.transform(x, y)
    print(f"  {lo:.5f},{la:.5f}  {c:,} trips")
