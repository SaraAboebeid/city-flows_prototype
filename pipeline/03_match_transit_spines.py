"""Map-match transit trips (Train/Tram, Bus, Boat) onto OSM route geometry.

For each trip pick the OSM route spine of the right mode minimising
dist(origin, line) + dist(destination, line), with both endpoints within
MAXSNAP metres, then cut the sub-path between the two projections.
Trips with no acceptable route keep their straight line, flagged 'straight'.

Writes _derived/trips_matched.parquet (all 1.28M trips, transit re-routed).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
import os
import numpy as np
import pandas as pd
import geopandas as gpd
import pyarrow as pa
import pyarrow.parquet as pq
from shapely.geometry import Point, LineString
from shapely.ops import substring
from shapely import STRtree
from pyproj import Transformer

TRIPS = os.path.join(DER, "trips.parquet")
ROUTES = os.path.join(DER, "transit_routes.gpkg")
OUT = os.path.join(DER, "trips_matched.parquet")

MAXSNAP = 900.0      # metres an endpoint may sit from the route
MINLEN = 150.0       # ignore degenerate sub-paths

MODEMAP = {
    "Train/Tram": ("tram", "train"),
    "Bus": ("bus",),
    "Boat": ("ferry",),
}

to3006 = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)
to4326 = Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)

routes = gpd.read_file(ROUTES)
print(f"loaded {len(routes)} OSM route spines")

# one STRtree per dataset-mode
trees = {}
for dmode, omodes in MODEMAP.items():
    sub = routes[routes["mode"].isin(omodes)].reset_index(drop=True)
    geoms = list(sub.geometry.values)
    trees[dmode] = (geoms, STRtree(geoms), sub)
    print(f"  {dmode:12s} <- {omodes}  {len(geoms)} spines")

df = pq.read_table(TRIPS).to_pandas()
print(f"loaded {len(df):,} trips")

is_transit = df["mode"].isin(MODEMAP)
print(f"transit trips to match: {is_transit.sum():,}")

match_col = np.array(["n/a"] * len(df), dtype=object)
match_col[is_transit.values] = "straight"
new_lon = df["lon"].tolist()
new_lat = df["lat"].tolist()

idxs = np.flatnonzero(is_transit.values)
stats = {"matched": 0, "no_candidate": 0, "too_short": 0}

for n, i in enumerate(idxs):
    if n % 25000 == 0:
        print(f"  {n:,}/{len(idxs):,}  matched={stats['matched']:,}", flush=True)

    lo, la = new_lon[i], new_lat[i]
    ox, oy = to3006.transform(lo[0], la[0])
    dx, dy = to3006.transform(lo[-1], la[-1])
    po, pd_ = Point(ox, oy), Point(dx, dy)

    geoms, tree, _ = trees[df["mode"].iat[i]]
    cand = tree.query(po.buffer(MAXSNAP))
    if len(cand) == 0:
        stats["no_candidate"] += 1
        continue

    best, bestscore = None, np.inf
    for ci in cand:
        g = geoms[ci]
        d1 = g.distance(po)
        d2 = g.distance(pd_)
        if d1 > MAXSNAP or d2 > MAXSNAP:
            continue
        s = d1 + d2
        if s < bestscore:
            bestscore, best = s, g
    if best is None:
        stats["no_candidate"] += 1
        continue

    a, b = best.project(po), best.project(pd_)
    rev = a > b
    if rev:
        a, b = b, a
    if b - a < MINLEN:
        stats["too_short"] += 1
        continue

    seg = substring(best, a, b)
    if seg.is_empty or seg.geom_type != "LineString" or len(seg.coords) < 2:
        stats["too_short"] += 1
        continue

    xs, ys = np.array(seg.coords).T
    if rev:
        xs, ys = xs[::-1], ys[::-1]
    # keep the true trip endpoints, bridging the snap gap
    lon2, lat2 = to4326.transform(xs, ys)
    lon2 = np.concatenate([[lo[0]], lon2, [lo[-1]]])
    lat2 = np.concatenate([[la[0]], lat2, [la[-1]]])
    new_lon[i] = lon2.tolist()
    new_lat[i] = lat2.tolist()
    match_col[i] = "osm_route"
    stats["matched"] += 1

df["lon"] = new_lon
df["lat"] = new_lat
df["n_pts"] = [len(v) for v in new_lon]
df["routed"] = df["n_pts"] > 2
df["match"] = match_col

pq.write_table(pa.Table.from_pandas(df, preserve_index=False), OUT,
               compression="zstd")

print("\n--- results ---")
for k, v in stats.items():
    print(f"  {k:14s} {v:>8,}")
t = is_transit.sum()
print(f"  match rate     {100*stats['matched']/t:.1f}% of transit trips")
print(f"\nrouted geometry overall: "
      f"{df['routed'].sum():,}/{len(df):,} ({100*df['routed'].mean():.1f}%)")
print(f"wrote {OUT}  ({os.path.getsize(OUT)/1e6:.0f} MB)")
