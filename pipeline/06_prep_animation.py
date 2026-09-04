"""Sample trips and pack them into a compact binary payload for the
deck.gl TripsLayer animation.

Encoding (little-endian):
  meta   : per trip -> 8 x int32
           t_start, t_end, mode, npts, purpose, age, sex, status
  coords : per trip -> int32 lon0,lat0 (1e-5 deg) then (npts-1) x int16 deltas
Per-vertex timestamps are derived client-side from cumulative distance.
"""
import os, sys, json, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DER  # noqa: E402

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from shapely.geometry import LineString

for cand in ("trips_final.parquet", "trips_routed2.parquet",
             "trips_routed.parquet", "trips_matched.parquet", "trips.parquet"):
    SRC = os.path.join(DER, cand)
    if os.path.exists(SRC):
        break
OUT = os.path.join(DER, "anim_payload.json")

N_TARGET = 45000
SIMPLIFY_DEG = 0.00018     # ~20 m
MAXD = 30000               # max int16 delta in 1e-5 deg units

MODES = ["Car", "Train/Tram", "Bus", "Bicycle/E-bike", "Walking", "Boat", "Other"]
PURPOSES = ["Home", "Work", "Leisure", "Grocery", "Pickup/Dropoff child",
            "Education", "Shopping", "Travel", "Healthcare", "Other"]
AGES = ["16-24", "25-44", "45-64", "65+", "Unknown"]
SEXES = ["Women", "Men", "Unknown"]
STATUS = ["Working", "Studying", "At home", "Other/Unknown"]

IDX = {name: {v: i for i, v in enumerate(vals)} for name, vals in
       (("mode", MODES), ("purpose", PURPOSES), ("age", AGES),
        ("sex", SEXES), ("status", STATUS))}


def bucket(val, name, fallback):
    return IDX[name].get(val, IDX[name][fallback])


print(f"reading {os.path.basename(SRC)}")
df = pq.read_table(SRC).to_pandas()
print(f"{len(df):,} trips")

df["mbucket"] = [m if m in IDX["mode"] else "Other" for m in df["mode"]]
has_demo = "age_band" in df.columns

rng = np.random.default_rng(42)
frac = N_TARGET / len(df)
keep = []
for m, g in df.groupby("mbucket"):
    k = min(max(1, int(round(len(g) * frac))), len(g))
    keep.append(g.sample(k, random_state=42))
s = pd.concat(keep).sample(frac=1.0, random_state=7).reset_index(drop=True)
print(f"sampled {len(s):,} trips")
print(s.mbucket.value_counts().to_string())

meta, coord_parts = [], []
kept = dropped = 0

cols = [s.lon.values, s.lat.values, s.t_start.values, s.t_end.values,
        s.mbucket.values, s.purpose_to.values]
if has_demo:
    cols += [s.age_band.astype(str).values, s.sex.astype(str).values,
             s.status.astype(str).values]
else:
    n = len(s)
    cols += [np.array(["Unknown"] * n)] * 2 + [np.array(["Other/Unknown"] * n)]

for lon, lat, t0, t1, mb, pp, ag, sx, st in zip(*cols):
    lo = np.asarray(lon, dtype=float)
    la = np.asarray(lat, dtype=float)
    if len(lo) < 2:
        dropped += 1
        continue
    if len(lo) > 2:
        line = LineString(np.column_stack([lo, la])).simplify(SIMPLIFY_DEG)
        if len(line.coords) >= 2:
            c = np.asarray(line.coords)
            lo, la = c[:, 0], c[:, 1]

    q = np.column_stack([np.round(lo * 1e5), np.round(la * 1e5)]).astype(np.int64)
    while True:
        d = np.abs(np.diff(q, axis=0)).max(axis=1)
        bad = np.flatnonzero(d > MAXD)
        if bad.size == 0:
            break
        q = np.insert(q, bad + 1, (q[bad] + q[bad + 1]) // 2, axis=0)

    if len(q) < 2 or len(q) > 4000:
        dropped += 1
        continue

    coord_parts.append(q[0].astype(np.int32).tobytes())
    coord_parts.append(np.diff(q, axis=0).astype(np.int16).tobytes())
    meta.append((int(t0), int(t1), IDX["mode"][mb], len(q),
                 bucket(pp, "purpose", "Other"),
                 bucket(ag, "age", "Unknown"),
                 bucket(sx, "sex", "Unknown"),
                 bucket(st, "status", "Other/Unknown")))
    kept += 1

meta_arr = np.asarray(meta, dtype=np.int32)
coords_blob = b"".join(coord_parts)

TRANSIT = ("Train/Tram", "Bus", "Boat")
tr = df["mode"].isin(TRANSIT)
transit_pct = (100.0 * (tr & df["match"].isin(["osm_route", "osm_network"])).sum()
               / max(int(tr.sum()), 1)) if "match" in df.columns else 0.0

json.dump({
    "total_trips": int(len(df)), "total_persons": 575753,
    "sample": int(kept), "transit_pct": round(float(transit_pct), 1),
    "transit_trips": int(tr.sum()),
}, open(os.path.join(DER, "anim_stats.json"), "w", encoding="utf-8"), indent=1)

json.dump({
    "modes": MODES, "purposes": PURPOSES,
    "ages": AGES, "sexes": SEXES, "status": STATUS,
    "n": kept,
    "meta": base64.b64encode(meta_arr.tobytes()).decode(),
    "coords": base64.b64encode(coords_blob).decode(),
}, open(OUT, "w", encoding="utf-8"), separators=(",", ":"))

print(f"\ntransit with real network geometry: {transit_pct:.1f}%")
print(f"kept {kept:,} trips ({dropped:,} dropped), "
      f"{int(meta_arr[:,3].sum()):,} vertices")
print(f"coords {len(coords_blob)/1e6:.2f} MB raw -> payload "
      f"{os.path.getsize(OUT)/1e6:.2f} MB")
