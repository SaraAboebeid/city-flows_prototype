"""Re-trace a sample of trips along the real OSM streets, for the moving
trips in the STREET FLOWS view.

The dataset's routes join intersections with straight chords that cut across
curving streets (see stage 12). Animated as-is they slice through blocks. Here
every long chord is replaced by the street path between its two junctions
(A* on the mode's network, as in stage 12), so the moving trips run exactly on
the segments they are counted on. Network-matched transit keeps its matched
path; unmatched ('straight') transit is left out - it is on no street.

Writes flow_sample.json: meta i32 x 10 per trip
  (t0, t1, mode, npts, purpose, age, sex, status, plausible, hood)
  + coords (i32 first vertex, i16 deltas, 1e-5 deg), both gzip + base64.
"""
import os, sys, json, gzip, base64, heapq, math, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER  # noqa: E402

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import LineString

N_SAMPLE = 40000
SHORT_M, JUNC_M = 60.0, 1.5
SIMPLIFY_M = 3.0
MODES = ["Car", "Train/Tram", "Bus", "Bicycle/E-bike", "Walking", "Boat", "Other"]
PURPOSES = ["Home", "Work", "Leisure", "Grocery", "Pickup/Dropoff child",
            "Education", "Shopping", "Travel", "Healthcare", "Other"]
AGES = ["16-24", "25-44", "45-64", "65+", "Unknown"]
SEXES = ["Women", "Men", "Unknown"]
STATUS = ["Working", "Studying", "At home", "Other/Unknown"]
NET_OF_MODE = {"Car": "drive", "Taxi": "drive", "Moped": "drive",
               "Transportation service": "drive", "Bicycle/E-bike": "bike",
               "Walking": "walk"}
EXCL = {   # same OSMnx-style network filters as stage 12
    "drive": {"abandoned", "bridleway", "bus_guideway", "construction", "corridor",
              "cycleway", "elevator", "escalator", "footway", "path", "pedestrian",
              "planned", "platform", "proposed", "raceway", "steps", "track", "busway"},
    "bike": {"abandoned", "bus_guideway", "construction", "corridor", "elevator",
             "escalator", "footway", "motorway", "motorway_link", "planned",
             "platform", "proposed", "raceway", "steps"},
    "walk": {"abandoned", "bus_guideway", "construction", "cycleway", "motorway",
             "motorway_link", "planned", "platform", "proposed", "raceway"},
    "all": set(),
}

to3006 = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)
to4326 = Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)

# ---------- street network + junction graph ----------
st = pq.read_table(os.path.join(DER, "streets.parquet"),
                   columns=["edge_id", "highway", "length_m", "lon", "lat"])
NE = st.num_rows
hwy = np.asarray(st.column("highway").to_pylist(), dtype=object)
seglen = np.asarray(st.column("length_m"))
lo_a, la_a = st.column("lon").combine_chunks(), st.column("lat").combine_chunks()
off = np.asarray(lo_a.offsets)
X, Y = tf_xy = to3006.transform(np.asarray(lo_a.values), np.asarray(la_a.values))
first_v, last_v = off[:-1], off[1:] - 1
ends = np.column_stack([np.r_[X[first_v], X[last_v]], np.r_[Y[first_v], Y[last_v]]])
keys = np.round(ends * 10).astype(np.int64)
_, jid = np.unique(keys[:, 0] * 4_000_000_000 + keys[:, 1], return_inverse=True)
NJ = int(jid.max()) + 1
ju, jv = jid[:NE], jid[NE:]
JXY = np.zeros((NJ, 2)); JXY[ju] = ends[:NE]; JXY[jv] = ends[NE:]
jtree = cKDTree(JXY)
adj = [[] for _ in range(NJ)]
for e in range(NE):
    a, b = int(ju[e]), int(jv[e])
    if a != b:
        adj[a].append((b, e)); adj[b].append((a, e))
allowed = {n: np.array([h not in EXCL[n] for h in hwy]) for n in EXCL}
print(f"{NE:,} segments, {NJ:,} junctions", flush=True)


def astar(u, v, net, bound):
    """ordered [(segment, forward)] from junction u to v, or None"""
    ok = allowed[net]
    tx, ty = JXY[v]
    dist, prev = {u: 0.0}, {}
    pq_ = [(math.hypot(JXY[u][0] - tx, JXY[u][1] - ty), 0.0, u)]
    while pq_:
        f, g, n = heapq.heappop(pq_)
        if n == v:
            path = []
            while n != u:
                p, e = prev[n]
                path.append((e, int(ju[e]) == p))   # forward if we enter at its start
                n = p
            return path[::-1]
        if g > dist.get(n, 1e18) or f > bound:
            continue
        for m, e in adj[n]:
            if not ok[e]:
                continue
            g2 = g + seglen[e]
            if g2 < dist.get(m, 1e18):
                dist[m] = g2; prev[m] = (n, e)
                heapq.heappush(pq_, (g2 + math.hypot(JXY[m][0] - tx, JXY[m][1] - ty), g2, m))
    return None


cache = {}

# ---------- sample ----------
df = pq.read_table(os.path.join(DER, "trips_final2.parquet"),
                   columns=["lon", "lat", "t_start", "t_end", "mode", "match", "n_pts",
                            "plausible", "purpose_to", "age_band", "sex", "status",
                            "neighborhood"]).to_pandas()
cand = df[df.plausible & (((df["match"] == "n/a") & (df.n_pts > 2)) |
                          df["match"].isin(["osm_route", "osm_network"]))].copy()
cand["mb"] = [m if m in MODES else "Other" for m in cand["mode"]]
frac = N_SAMPLE / len(cand)
s = pd.concat([g.sample(min(max(1, round(len(g) * frac)), len(g)), random_state=11)
               for _, g in cand.groupby("mb")]).sample(frac=1.0, random_state=5)
del df, cand
print(f"sampled {len(s):,} trips", flush=True)

hoods = sorted(os.path.basename(p)[22:-3] for p in glob.glob(os.path.join(DATA, "*.db")))
HOOD = {h: i for i, h in enumerate(hoods)}
idx = lambda vocab, fb: (lambda v: vocab.index(v) if v in vocab else vocab.index(fb))
f_mode, f_pur = idx(MODES, "Other"), idx(PURPOSES, "Other")
f_age, f_sex, f_st = idx(AGES, "Unknown"), idx(SEXES, "Unknown"), idx(STATUS, "Other/Unknown")

meta, parts = [], []
chords = retraced = 0
for k, r in enumerate(s.itertuples(index=False)):
    x, y = to3006.transform(np.asarray(r.lon, float), np.asarray(r.lat, float))
    if r.match == "n/a":
        net = NET_OF_MODE.get(r.mode, "all")
        px, py = [x[0]], [y[0]]
        for i in range(len(x) - 1):
            L = math.hypot(x[i+1] - x[i], y[i+1] - y[i])
            path = None
            if L > SHORT_M:
                chords += 1
                da, a = jtree.query((x[i], y[i]))
                db, b = jtree.query((x[i+1], y[i+1]))
                if da <= JUNC_M and db <= JUNC_M and a != b:
                    key = (net, int(a), int(b))
                    path = cache.get(key, 0)
                    if path == 0:
                        path = astar(int(a), int(b), net, 1.6 * L + 60)
                        cache[key] = path
            if path:
                retraced += 1
                for e, fwd in path:
                    ex, ey = X[off[e]:off[e+1]], Y[off[e]:off[e+1]]
                    if not fwd:
                        ex, ey = ex[::-1], ey[::-1]
                    px.extend(ex[1:]); py.extend(ey[1:])
            else:
                px.append(x[i+1]); py.append(y[i+1])
        x, y = np.asarray(px), np.asarray(py)
    if len(x) > 2:
        c = np.asarray(LineString(np.column_stack([x, y])).simplify(SIMPLIFY_M).coords)
        x, y = c[:, 0], c[:, 1]
    lon, lat = to4326.transform(x, y)
    q = np.column_stack([np.round(np.asarray(lon) * 1e5), np.round(np.asarray(lat) * 1e5)]).astype(np.int64)
    keep = np.r_[True, np.any(np.diff(q, axis=0) != 0, axis=1)]      # drop repeats
    q = q[keep]
    if len(q) < 2:
        continue
    while True:
        bad = np.flatnonzero(np.abs(np.diff(q, axis=0)).max(axis=1) > 30000)
        if bad.size == 0:
            break
        q = np.insert(q, bad + 1, (q[bad] + q[bad + 1]) // 2, axis=0)
    parts += [q[0].astype(np.int32).tobytes(), np.diff(q, axis=0).astype(np.int16).tobytes()]
    meta.append((int(r.t_start), int(r.t_end), f_mode(r.mb), len(q), f_pur(r.purpose_to),
                 f_age(str(r.age_band)), f_sex(str(r.sex)), f_st(str(r.status)),
                 1, HOOD.get(r.neighborhood, 255)))
    if (k + 1) % 5000 == 0:
        print(f"  {k+1:,} trips | chords re-traced {100*retraced/max(chords,1):.1f}% "
              f"| cache {len(cache):,}", flush=True)

meta_a = np.asarray(meta, np.int32)
coords = b"".join(parts)
b64gz = lambda raw: base64.b64encode(gzip.compress(raw, 9)).decode()
out = os.path.join(DER, "flow_sample.json")
json.dump({"n": len(meta), "fields": 10, "meta": b64gz(meta_a.tobytes()),
           "coords": b64gz(coords)}, open(out, "w"), separators=(",", ":"))
print(f"\n{len(meta):,} trips, {int(meta_a[:, 3].sum()):,} vertices | "
      f"long chords re-traced along streets: {100*retraced/max(chords,1):.1f}% | "
      f"{os.path.getsize(out)/1e6:.2f} MB -> {out}")
print(s.mb.value_counts().to_string())
