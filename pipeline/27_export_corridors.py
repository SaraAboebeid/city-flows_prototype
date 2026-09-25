"""Pack the corridor comparison (stage 26) for the corridor map.

Geometry: the drivable, named OSM segments of every compared corridor, in the
same polyline encoding as the other payloads (int32 first vertex + int16
deltas at 1e-5 degrees, gzipped, base64). Each segment carries the index of
its corridor, so the map colours whole corridors at once.

Values are per corridor, not per segment: the comparison only holds at
corridor level (stage 26), and drawing a corridor's single value on all of its
segments is what makes that visible.

Writes ../gothenburg-corridors-js/data/corridors.json and config.json.
"""
import os, sys, json, gzip, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DER, CORRWEB, carto_key  # noqa: E402

import numpy as np
import pandas as pd
import geopandas as gpd
import pyarrow.parquet as pq
from pyproj import Transformer

DRIVE_EXCL = {"footway", "path", "cycleway", "pedestrian", "steps", "track",
              "bridleway", "corridor", "platform", "elevator", "escalator",
              "construction", "proposed", "busway", "bus_guideway"}
MIN_CROSS = 20                      # same threshold as stage 26

OUT = os.path.join(CORRWEB, "data")
os.makedirs(OUT, exist_ok=True)
blob = lambda b: base64.b64encode(gzip.compress(b if isinstance(b, bytes) else
                                                np.ascontiguousarray(b).tobytes(), 9)).decode()

# ---------- the corridor table ----------
C = pd.read_csv(os.path.join(DER, "corridors.csv"))
C = C.sort_values("phone20_share", ascending=False).reset_index(drop=True)
idx_of = {n: i for i, n in enumerate(C.corridor)}
print(f"corridors: {len(C):,} | well observed: {int((C.cross_20 >= MIN_CROSS).sum()):,}")

# ---------- their segments ----------
st = pq.read_table(os.path.join(DER, "streets.parquet"),
                   columns=["highway", "name", "length_m", "lon", "lat"])
hwy = np.asarray(st.column("highway").to_pylist(), dtype=object)
name = pd.Series(st.column("name").to_pylist(), dtype="object").fillna("").str.strip().values
keep = np.flatnonzero([h not in DRIVE_EXCL and n in idx_of for h, n in zip(hwy, name)])
lo = st.column("lon").combine_chunks(); la = st.column("lat").combine_chunks()
off = np.asarray(lo.offsets); LON = np.asarray(lo.values); LAT = np.asarray(la.values)

parts, npts, cidx = [], [], []
sumx = np.zeros(len(C)); sumy = np.zeros(len(C)); cnt = np.zeros(len(C))
for e in keep:
    a, b = off[e], off[e + 1]
    q = np.column_stack([np.round(LON[a:b] * 1e5), np.round(LAT[a:b] * 1e5)]).astype(np.int64)
    q = q[np.insert(np.abs(np.diff(q, axis=0)).max(axis=1) > 0, 0, True)]      # drop repeats
    if len(q) < 2:
        continue
    while True:                                   # int16 deltas: split long jumps
        bad = np.flatnonzero(np.abs(np.diff(q, axis=0)).max(axis=1) > 30000)
        if bad.size == 0:
            break
        q = np.insert(q, bad + 1, (q[bad] + q[bad + 1]) // 2, axis=0)
    k = idx_of[name[e]]
    parts += [q[0].astype(np.int32).tobytes(), np.diff(q, axis=0).astype(np.int16).tobytes()]
    npts.append(len(q)); cidx.append(k)
    sumx[k] += q[:, 0].mean(); sumy[k] += q[:, 1].mean(); cnt[k] += 1
print(f"segments packed: {len(npts):,}")

# a point to fly to when a corridor is picked from the list
cnt = np.maximum(cnt, 1)
C["lon"] = (sumx / cnt) / 1e5
C["lat"] = (sumy / cnt) / 1e5

# ---------- count sites ----------
to4326 = Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)
gt = gpd.read_parquet(os.path.join(DER, "groundtruth_gbg.parquet"))
p = gt.geometry.representative_point()
glon, glat = to4326.transform(p.x.values, p.y.values)
ground = [{"lon": round(float(a), 5), "lat": round(float(b), 5), "adt": int(v),
           "src": "highway" if s == "highway" else "local", "name": (n or "")}
          for a, b, v, s, n in zip(glon, glat, gt.adt.values, gt.source.values, gt.name.values)]

num = lambda v, d=1: None if v is None or not np.isfinite(v) else round(float(v), d)
corridors = [{"name": r.corridor, "km": num(r.osm_len_km),
              "syn": num(r.syn_mean, 0), "ph": num(r.phone_mean, 1), "ph20": num(r.phone20_mean, 1),
              "synS": num(r.syn_share, 2), "phS": num(r.phone_share, 2), "ph20S": num(r.phone20_share, 2),
              "ratio": num(r.log2_ratio, 2), "adt": num(r.adt_mean, 0),
              "nc": 0 if not np.isfinite(r.n_counts) else int(r.n_counts),
              "cross": int(r.cross_20), "lon": num(r.lon, 5), "lat": num(r.lat, 5)}
             for r in C.itertuples()]

out = {
    "n": len(npts),
    "coords": blob(b"".join(parts)),
    "npts": blob(np.asarray(npts, np.uint16)),
    "cidx": blob(np.asarray(cidx, np.uint16)),
    "corridors": corridors,
    "min_crossings": MIN_CROSS,
    "ground": ground,
    "stats": json.load(open(os.path.join(DER, "corridor_compare.json"), encoding="utf-8")),
}
json.dump(out, open(os.path.join(OUT, "corridors.json"), "w", encoding="utf-8"),
          ensure_ascii=False, separators=(",", ":"))

key = carto_key()
json.dump({"cartoApiKey": key}, open(os.path.join(CORRWEB, "config.json"), "w"), indent=1)
print("basemap key: " + ("written to config.json" if key else "MISSING - see carto_api_key.txt"))
sz = os.path.getsize(os.path.join(OUT, "corridors.json"))
print(f"wrote corridors.json ({sz/1e6:.2f} MB, {len(corridors):,} corridors, "
      f"{len(ground)} count sites) -> {OUT}")
