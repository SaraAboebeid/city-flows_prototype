"""Are the walking trips physically plausible?

Measures true along-route length (haversine over the polyline), duration from
the trip's own start/end times, and the implied average speed, per mode.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DER  # noqa: E402

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

SRC = os.path.join(DER, "trips_final.parquet")
R = 6371008.8


def polyline_km(lon, lat):
    """great-circle length along a polyline, in km"""
    if len(lon) < 2:
        return 0.0
    la = np.radians(lat); lo = np.radians(lon)
    dla = np.diff(la); dlo = np.diff(lo)
    a = np.sin(dla/2)**2 + np.cos(la[:-1])*np.cos(la[1:])*np.sin(dlo/2)**2
    return float((2*R*np.arcsin(np.sqrt(np.clip(a, 0, 1)))).sum()/1000)


pf = pq.ParquetFile(SRC)
rows = []
for batch in pf.iter_batches(batch_size=50000,
                             columns=["mode", "lon", "lat", "t_start", "t_end",
                                      "match", "n_pts"]):
    d = batch.to_pydict()
    for m, lo, la, t0, t1, mt, npz in zip(d["mode"], d["lon"], d["lat"],
                                          d["t_start"], d["t_end"],
                                          d["match"], d["n_pts"]):
        km = polyline_km(np.asarray(lo), np.asarray(la))
        mins = (t1 - t0) / 60.0
        rows.append((m, km, mins, km/(mins/60) if mins > 0 else np.nan,
                     mt, npz))

df = pd.DataFrame(rows, columns=["mode", "km", "min", "kmh", "match", "n_pts"])
print(f"{len(df):,} trips measured\n")

print("=== along-route distance (km) by mode ===")
print(df.groupby("mode").km.describe(
    percentiles=[.5, .9, .99])[["count", "50%", "90%", "99%", "max"]]
    .round(2).to_string())

print("\n=== implied average speed (km/h) by mode ===")
print(df.groupby("mode").kmh.describe(
    percentiles=[.5, .9, .99])[["50%", "90%", "99%", "max"]]
    .round(1).to_string())

w = df[df["mode"] == "Walking"]
print(f"\n=== WALKING: {len(w):,} trips ===")
print(f"  median {w.km.median():.2f} km over {w['min'].median():.0f} min "
      f"= {w.kmh.median():.1f} km/h")
for lim in (5, 10, 20, 40):
    n = (w.km > lim).sum()
    print(f"  longer than {lim:>2} km : {n:>7,}  ({100*n/len(w):.2f}%)")
for lim in (7, 10, 15):
    n = (w.kmh > lim).sum()
    print(f"  faster than {lim:>2} km/h: {n:>7,}  ({100*n/len(w):.2f}%)")

print("\n  straight-line vs routed geometry among long walks (>10 km):")
lw = w[w.km > 10]
if len(lw):
    print("   ", lw.n_pts.le(2).mean().round(3), "share with only 2 points")
    print("   ", lw.groupby(lw.n_pts <= 2).km.median().round(1).to_dict())

print("\n=== the 8 longest walking trips ===")
print(w.nlargest(8, "km")[["km", "min", "kmh", "n_pts", "match"]]
      .round(2).to_string(index=False))
