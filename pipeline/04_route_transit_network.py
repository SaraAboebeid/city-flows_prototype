
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
"""Second pass: route transit trips over a *network* of OSM transit lines,
so journeys that need a transfer between lines still follow real track.

Builds one graph per dataset mode from all route spines (vertices snapped to a
grid so shared track merges), adds short transfer edges between nearby nodes,
then runs one Dijkstra per unique origin node and reconstructs every
destination path from that origin's predecessor tree.
"""
import os, sys, collections
import numpy as np
import pandas as pd
import geopandas as gpd
import pyarrow as pa, pyarrow.parquet as pq
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
from pyproj import Transformer

SRC = os.path.join(DER, sys.argv[1] if len(sys.argv) > 1 else "trips_matched.parquet")
OUT = os.path.join(DER, sys.argv[2] if len(sys.argv) > 2 else "trips_routed.parquet")

GRID = 40.0          # m, vertex snapping (coarser => far fewer Dijkstra nodes)
TRANSFER = 160.0     # m, max walk between lines
TR_PENALTY = 250.0   # m-equivalent cost of a transfer
MAXSNAP = float(sys.argv[3]) if len(sys.argv) > 3 else 1200.0     # m, endpoint -> network
MODEMAP = {"Train/Tram": ("tram", "train"), "Bus": ("bus",), "Boat": ("ferry",)}

to3006 = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)
to4326 = Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)

routes = gpd.read_file(os.path.join(DER, "transit_routes.gpkg"))
df = pq.read_table(SRC).to_pandas()
print(f"{len(df):,} trips loaded; unmatched transit to fix: "
      f"{(df['match'] == 'straight').sum():,}")


def build_graph(sub):
    """spines -> (nodes Nx2, csr graph)"""
    keys = {}
    coords = []
    edges = collections.defaultdict(lambda: np.inf)

    def nid(p):
        k = (int(round(p[0] / GRID)), int(round(p[1] / GRID)))
        if k not in keys:
            keys[k] = len(coords)
            coords.append((k[0] * GRID, k[1] * GRID))
        return keys[k]

    for geom in sub.geometry.values:
        c = np.asarray(geom.coords)
        ids = [nid(p) for p in c]
        d = np.hypot(*np.diff(c, axis=0).T)
        for a, b, w in zip(ids[:-1], ids[1:], d):
            if a == b:
                continue
            lo, hi = (a, b) if a < b else (b, a)
            if w < edges[(lo, hi)]:
                edges[(lo, hi)] = w

    nodes = np.asarray(coords, dtype=float)
    tree = cKDTree(nodes)
    for a, b in tree.query_pairs(TRANSFER):
        lo, hi = (a, b) if a < b else (b, a)
        w = np.hypot(*(nodes[a] - nodes[b])) + TR_PENALTY
        if w < edges[(lo, hi)]:
            edges[(lo, hi)] = w

    if not edges:
        return nodes, None, tree
    ij = np.array(list(edges.keys()))
    w = np.array(list(edges.values()))
    n = len(nodes)
    g = coo_matrix((np.concatenate([w, w]),
                    (np.concatenate([ij[:, 0], ij[:, 1]]),
                     np.concatenate([ij[:, 1], ij[:, 0]]))),
                   shape=(n, n)).tocsr()
    return nodes, g, tree


lon_col = df["lon"].tolist()
lat_col = df["lat"].tolist()
match_col = df["match"].to_numpy(dtype=object)
fixed = 0
failed = 0

for dmode, omodes in MODEMAP.items():
    sel = np.flatnonzero((df["mode"] == dmode).to_numpy()
                         & (match_col == "straight"))
    if sel.size == 0:
        continue
    sub = routes[routes["mode"].isin(omodes)]
    if sub.empty:
        continue
    nodes, g, tree = build_graph(sub)
    if g is None:
        continue
    print(f"\n{dmode}: {sel.size:,} trips, graph {len(nodes):,} nodes", flush=True)

    ox, oy = to3006.transform([lon_col[i][0] for i in sel],
                             [lat_col[i][0] for i in sel])
    dx, dy = to3006.transform([lon_col[i][-1] for i in sel],
                             [lat_col[i][-1] for i in sel])
    do, io = tree.query(np.column_stack([ox, oy]), distance_upper_bound=MAXSNAP)
    dd, idd = tree.query(np.column_stack([dx, dy]), distance_upper_bound=MAXSNAP)

    ok = np.isfinite(do) & np.isfinite(dd) & (io != len(nodes)) & (idd != len(nodes))
    print(f"  endpoints snapped: {ok.sum():,}/{sel.size:,}", flush=True)

    order = collections.defaultdict(list)
    for k in np.flatnonzero(ok):
        order[int(io[k])].append(k)

    done = 0
    for si, (src, members) in enumerate(order.items()):
        if si % 400 == 0:
            print(f"  dijkstra {si:,}/{len(order):,} sources, fixed={fixed:,}",
                  flush=True)
        dist, pred = dijkstra(g, directed=False, indices=src,
                              return_predecessors=True)
        for k in members:
            tgt = int(idd[k])
            if not np.isfinite(dist[tgt]):
                failed += 1
                continue
            path = []
            cur = tgt
            guard = 0
            while cur != src and cur >= 0 and guard < 20000:
                path.append(cur)
                cur = pred[cur]
                guard += 1
            if cur != src:
                failed += 1
                continue
            path.append(src)
            path.reverse()
            if len(path) < 2:
                failed += 1
                continue
            pts = nodes[path]
            lo, la = to4326.transform(pts[:, 0], pts[:, 1])
            i = sel[k]
            lon_col[i] = np.concatenate([[lon_col[i][0]], lo, [lon_col[i][-1]]]).tolist()
            lat_col[i] = np.concatenate([[lat_col[i][0]], la, [lat_col[i][-1]]]).tolist()
            match_col[i] = "osm_network"
            fixed += 1
            done += 1
    print(f"  {dmode}: routed {done:,}", flush=True)

df["lon"] = lon_col
df["lat"] = lat_col
df["match"] = match_col
df["n_pts"] = [len(v) for v in lon_col]
df["routed"] = df["n_pts"] > 2

pq.write_table(pa.Table.from_pandas(df, preserve_index=False), OUT,
               compression="zstd")

print("\n--- final ---")
print(df["match"].value_counts().to_string())
tr = df["mode"].isin(MODEMAP)
good = tr & df["match"].isin(["osm_route", "osm_network"])
print(f"\ntransit with real network geometry: {good.sum():,}/{tr.sum():,} "
      f"({100*good.sum()/tr.sum():.1f}%)")
print(f"overall routed: {df['routed'].sum():,}/{len(df):,} "
      f"({100*df['routed'].mean():.1f}%)")
print(f"wrote {OUT} ({os.path.getsize(OUT)/1e6:.0f} MB)")

