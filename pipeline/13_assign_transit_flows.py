"""Transit layer: project matched tram/train, bus and boat trips onto
deduplicated pieces of the OSM transit route spines.

These paths are INFERRED (stages 3-4: shortest paths over the transit network,
snapped to a 40 m grid), so they are kept apart from street flows and use a
looser snap. Unmatched ('straight') transit trips are excluded.

Writes transit_pieces.parquet, transit_flows_day.parquet,
       transit_flows_time.parquet
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DER  # noqa: E402

import numpy as np
import pandas as pd
import geopandas as gpd
import pyarrow as pa
import pyarrow.parquet as pq
from shapely.geometry import box
from pyproj import Transformer
from scipy.spatial import cKDTree

TRIPS = os.path.join(DER, "trips_final2.parquet")
ROUTES = os.path.join(DER, "transit_routes.gpkg")
PIECE_M = 60.0       # target transit piece length
DEDUPE_M = 30.0      # pieces whose midpoints share this grid are one piece
SNAP_M = 35.0        # inferred paths can sit ~28 m off the true track
SAMPLE_M = 20.0
BIN_S, H0 = 900, 3
NB = (24 - H0) * 3600 // BIN_S
GROUPS = {"Train/Tram": ("tram", "train"), "Bus": ("bus",), "Boat": ("ferry",)}
GNAMES = list(GROUPS)

to3006 = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)
to4326 = Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)

routes = gpd.read_file(ROUTES)
clip = box(299000, 6383900, 335000, 6417300)

pieces = []          # (group, x-array, y-array)
seen = set()
for gi, (g, omodes) in enumerate(GROUPS.items()):
    sub = routes[routes["mode"].isin(omodes)]
    for geom in sub.geometry.values:
        geom = geom.intersection(clip)
        parts = getattr(geom, "geoms", [geom])
        for part in parts:
            if part.is_empty or part.geom_type != "LineString" or part.length < 5:
                continue
            n = max(1, int(round(part.length / PIECE_M)))
            for k in range(n):
                a, b = part.length * k / n, part.length * (k + 1) / n
                pts = [part.interpolate(a + (b - a) * f) for f in (0, .25, .5, .75, 1)]
                mid = pts[2]
                key = (gi, int(mid.x // DEDUPE_M), int(mid.y // DEDUPE_M))
                if key in seen:
                    continue
                seen.add(key)
                pieces.append((gi, np.array([p.x for p in pts]),
                               np.array([p.y for p in pts])))
NPC = len(pieces)
print(f"{NPC:,} deduplicated transit pieces", flush=True)

trees = {}
for gi in range(len(GNAMES)):
    ids = [i for i, p in enumerate(pieces) if p[0] == gi]
    if not ids:
        continue
    pts, own = [], []
    for i in ids:
        _, xs, ys = pieces[i]
        for j in range(len(xs) - 1):
            L = np.hypot(xs[j+1]-xs[j], ys[j+1]-ys[j])
            m = max(2, int(L // 5) + 1)
            pts.append(np.column_stack([np.linspace(xs[j], xs[j+1], m),
                                        np.linspace(ys[j], ys[j+1], m)]))
            own.append(np.full(m, i))
    P = np.vstack(pts)
    trees[gi] = (cKDTree(P), np.concatenate(own), len(P))

day = np.zeros(NPC, np.int64)
tkeys = []
pf = pq.ParquetFile(TRIPS)
base = 0
for b in pf.iter_batches(batch_size=40000, columns=["lon", "lat", "t_start", "t_end",
                                                    "mode", "match", "plausible"]):
    n = b.num_rows
    mode = np.asarray(b.column("mode").to_pylist(), dtype=object)
    match = np.asarray(b.column("match").to_pylist(), dtype=object)
    pl = np.asarray(b.column("plausible").to_pylist(), dtype=bool)
    lon_b, lat_b = b.column("lon"), b.column("lat")
    offb = np.asarray(lon_b.offsets)
    flo, fla = np.asarray(lon_b.values), np.asarray(lat_b.values)
    t0 = np.asarray(b.column("t_start")); t1 = np.asarray(b.column("t_end"))
    for gi, g in enumerate(GNAMES):
        if gi not in trees:
            continue
        sel = np.flatnonzero((mode == g) & np.isin(match, ["osm_route", "osm_network"]) & pl)
        if sel.size == 0:
            continue
        tree, own, NPt = trees[gi]
        for i in sel:
            s, e = offb[i], offb[i+1]
            x, y = to3006.transform(flo[s:e], fla[s:e])
            seg = np.hypot(np.diff(x), np.diff(y))
            cum = np.r_[0, np.cumsum(seg)]
            tot = cum[-1]
            if tot <= 0:
                continue
            d = np.arange(SAMPLE_M / 2, tot, SAMPLE_M)
            sx, sy = np.interp(d, cum, x), np.interp(d, cum, y)
            _, ii = tree.query(np.column_stack([sx, sy]), distance_upper_bound=SNAP_M)
            hit = ii < NPt
            if not hit.any():
                continue
            pc = own[ii[hit]]
            tb = np.clip(np.floor((t0[i] + d[hit] / tot * (t1[i] - t0[i])) / BIN_S)
                         .astype(np.int64) - (H0 * 3600) // BIN_S, 0, NB - 1)
            day[np.unique(pc)] += 1
            tkeys.append(np.unique(pc.astype(np.int64) * NB + tb))
    base += n
    print(f"  {base:,} trips read", flush=True)

K = np.concatenate(tkeys) if tkeys else np.zeros(0, np.int64)
uk, uc = np.unique(K, return_counts=True)

grp = np.array([p[0] for p in pieces])
lon, lat = [], []
for _, xs, ys in pieces:
    lo, la = to4326.transform(xs, ys)
    lon.append(np.round(lo, 6).tolist()); lat.append(np.round(la, 6).tolist())
pq.write_table(pa.table({"piece_id": np.arange(NPC), "group": [GNAMES[g] for g in grp],
                         "lon": lon, "lat": lat}),
               os.path.join(DER, "transit_pieces.parquet"), compression="zstd")
dd = pd.DataFrame({"piece_id": np.arange(NPC), "group": [GNAMES[g] for g in grp],
                   "trips": day})
dd = dd[dd.trips > 0]
pq.write_table(pa.Table.from_pandas(dd, preserve_index=False),
               os.path.join(DER, "transit_flows_day.parquet"), compression="zstd")
td = pd.DataFrame({"piece_id": uk // NB, "bin": uk % NB, "trips": uc})
pq.write_table(pa.Table.from_pandas(td, preserve_index=False),
               os.path.join(DER, "transit_flows_time.parquet"), compression="zstd")

print(f"\npieces carrying trips: {len(dd):,}/{NPC:,}")
print(dd.groupby("group").trips.agg(["count", "max", "median"]).to_string())
