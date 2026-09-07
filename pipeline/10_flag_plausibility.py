"""Measure along-route distance for every trip and flag physically implausible
ones, so the map can be filtered to trips that could actually have happened.

Why distance and not speed: the dataset's schedule times come from
sampled_duration, drawn independently of the route (verified: schedule matches
sampled_duration 100% of the time, calculated_duration only 1.9%, and
calculated_duration is just distance / a flat 12 km/h). Implied speeds are
therefore meaningless for almost every trip. Distance, by contrast, is a real
property of the geometry we draw, so that is what gets flagged.

Writes trips_final2.parquet with dist_km + plausible columns.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DER  # noqa: E402

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

SRC = os.path.join(DER, "trips_final.parquet")
OUT = os.path.join(DER, "trips_final2.parquet")
R = 6371008.8

# generous upper bound on a single trip, per mode, in km
CAP = {
    "Walking": 5.0,
    "Bicycle/E-bike": 25.0,
    "Moped": 45.0,
    "Transportation service": 60.0,
}
DEFAULT_CAP = 80.0


def lengths_km(lon_arr, lat_arr):
    """along-route great-circle length for a ListArray pair, vectorised"""
    off = np.asarray(lon_arr.offsets, dtype=np.int64)
    lo = np.radians(np.asarray(lon_arr.values, dtype=np.float64))
    la = np.radians(np.asarray(lat_arr.values, dtype=np.float64))
    n = len(off) - 1
    if len(lo) < 2:
        return np.zeros(n)

    dla = np.diff(la)
    dlo = np.diff(lo)
    a = (np.sin(dla / 2) ** 2
         + np.cos(la[:-1]) * np.cos(la[1:]) * np.sin(dlo / 2) ** 2)
    seg = 2 * R * np.arcsin(np.sqrt(np.clip(a, 0, 1))) / 1000.0

    # drop segments that straddle a trip boundary
    valid = np.ones(len(seg), dtype=bool)
    bounds = off[1:-1] - 1
    bounds = bounds[(bounds >= 0) & (bounds < len(seg))]
    valid[bounds] = False

    cs = np.concatenate([[0.0], np.cumsum(np.where(valid, seg, 0.0))])
    starts = off[:-1]
    ends = off[1:] - 1
    ends = np.maximum(ends, starts)
    return cs[ends] - cs[starts]


pf = pq.ParquetFile(SRC)
tables, dists = [], []
seen = 0
for batch in pf.iter_batches(batch_size=50000):
    km = lengths_km(batch.column("lon"), batch.column("lat"))
    dists.append(km)
    tables.append(batch)
    seen += batch.num_rows
    print(f"  {seen:,} trips", flush=True)

tbl = pa.Table.from_batches(tables)
dist = np.concatenate(dists)
mode = np.asarray(tbl.column("mode"))

caps = np.full(len(dist), DEFAULT_CAP)
for m, c in CAP.items():
    caps[mode == m] = c
plaus = dist <= caps

tbl = tbl.append_column("dist_km", pa.array(np.round(dist, 4), pa.float32()))
tbl = tbl.append_column("plausible", pa.array(plaus, pa.bool_()))
pq.write_table(tbl, OUT, compression="zstd")

print(f"\nplausible: {plaus.sum():,}/{len(plaus):,} "
      f"({100*plaus.mean():.1f}%)\n")
print(f"{'mode':24s} {'trips':>9s} {'median km':>10s} {'max km':>8s} "
      f"{'cap':>6s} {'dropped':>9s} {'%':>6s}")
for m in sorted(set(mode.tolist())):
    sel = mode == m
    d = dist[sel]
    bad = (~plaus[sel]).sum()
    print(f"{m:24s} {sel.sum():>9,} {np.median(d):>10.2f} {d.max():>8.2f} "
          f"{CAP.get(m, DEFAULT_CAP):>6.0f} {bad:>9,} "
          f"{100*bad/max(sel.sum(),1):>5.1f}%")
print(f"\nwrote {OUT} ({os.path.getsize(OUT)/1e6:.0f} MB)")
