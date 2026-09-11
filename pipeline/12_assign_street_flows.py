"""Project every street-routed trip onto OSM street segments.

The dataset's routes run node-to-node on OSM, but through a *simplified*
routing graph: consecutive route vertices are often intersections joined by a
straight chord that cuts across the curving street between them. So:

  short route segments (<= SHORT_M)  midpoint (and 10 m) samples snap to the
                                     nearest street segment within SNAP_M
  long chords                        both ends snap to OSM junctions; an A*
                                     search on the mode's own network (drive /
                                     bike / walk, OSMnx filters) recovers the
                                     street path between them; cached per pair
  chords that cannot be matched      fall back to sampling (partial)

A trip counts once per street segment (per 15-min bin for the time cube).
Street-routed trips only (match == 'n/a'); transit is stage 13.

Writes street_flows_day.parquet, street_flows_time.parquet,
       street_flows_stats.json
"""
import os, sys, json, heapq, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DER  # noqa: E402

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Transformer
from scipy.spatial import cKDTree

TRIPS = os.path.join(DER, "trips_final2.parquet")
STREETS = os.path.join(DER, "streets.parquet")
OUT_DAY = os.path.join(DER, "street_flows_day.parquet")
OUT_TIME = os.path.join(DER, "street_flows_time.parquet")

SHORT_M = 60.0       # route segments up to this length use midpoint snapping
SNAP_M = 4.0         # sample -> street tolerance
JUNC_M = 1.5         # chord end -> OSM junction tolerance
SAMPLE_M = 10.0
DENSE_M = 2.0
BIN_S, H0 = 900, 3
NB = (24 - H0) * 3600 // BIN_S

MODES = ["Car", "Train/Tram", "Bus", "Bicycle/E-bike", "Walking", "Boat", "Other"]
PURPOSES = ["Home", "Work", "Leisure", "Grocery", "Pickup/Dropoff child",
            "Education", "Shopping", "Travel", "Healthcare", "Other"]
AGES = ["16-24", "25-44", "45-64", "65+", "Unknown"]
SEXES = ["Women", "Men", "Unknown"]
STATUS = ["Working", "Studying", "At home", "Other/Unknown"]
DIMS = {"mode": MODES, "purpose": PURPOSES, "age": AGES,
        "sex": SEXES, "status": STATUS}

# network each dataset mode can route on (OSMnx network_type filters)
NET_OF_MODE = {"Car": "drive", "Taxi": "drive", "Moped": "drive",
               "Transportation service": "drive",
               "Bicycle/E-bike": "bike", "Walking": "walk"}
NETS = ["drive", "bike", "walk", "all"]
EXCL = {
    "drive": {"abandoned", "bridleway", "bus_guideway", "construction", "corridor",
              "cycleway", "elevator", "escalator", "footway", "path", "pedestrian",
              "planned", "platform", "proposed", "raceway", "steps", "track",
              "busway"},
    "bike": {"abandoned", "bus_guideway", "construction", "corridor", "elevator",
             "escalator", "footway", "motorway", "motorway_link", "planned",
             "platform", "proposed", "raceway", "steps"},
    "walk": {"abandoned", "bus_guideway", "construction", "cycleway",
             "motorway", "motorway_link", "planned", "platform", "proposed",
             "raceway"},
    "all": set(),
}

tf = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)

# ---------- streets: densified KD-tree ----------
st = pq.read_table(STREETS, columns=["edge_id", "highway", "length_m", "lon", "lat"])
eids = np.asarray(st.column("edge_id"))
NE = int(eids.max()) + 1
hwy = np.asarray(st.column("highway").to_pylist(), dtype=object)
seglen = np.asarray(st.column("length_m"))
lon_a, lat_a = st.column("lon").combine_chunks(), st.column("lat").combine_chunks()
off = np.asarray(lon_a.offsets)
X, Y = tf.transform(np.asarray(lon_a.values), np.asarray(lat_a.values))
nv = np.diff(off)
e_of_v = np.repeat(eids, nv)
same = e_of_v[1:] == e_of_v[:-1]
i0 = np.flatnonzero(same)
dx, dy = X[i0 + 1] - X[i0], Y[i0 + 1] - Y[i0]
L = np.hypot(dx, dy)
ns = np.maximum(1, np.ceil(L / DENSE_M).astype(np.int64)) + 1
rep = np.repeat(np.arange(len(i0)), ns)
kk = np.arange(len(rep)) - np.repeat(np.cumsum(ns) - ns, ns)
fr = kk / (ns[rep] - 1)
tree = cKDTree(np.column_stack([X[i0][rep] + fr * dx[rep],
                                Y[i0][rep] + fr * dy[rep]]))
PE = e_of_v[i0][rep]
NP = len(PE)
del rep, kk, fr

# ---------- junction graph (segment endpoints) ----------
first_v, last_v = off[:-1], off[1:] - 1
ends = np.column_stack([np.r_[X[first_v], X[last_v]], np.r_[Y[first_v], Y[last_v]]])
keys = np.round(ends * 10).astype(np.int64)           # 0.1 m: shared OSM node
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
allowed = {n: np.array([h not in EXCL[n] for h in hwy]) for n in NETS}
print(f"{NE:,} segments, {NP:,} KD points, {NJ:,} junctions", flush=True)
del X, Y


def astar(u, v, net, bound):
    """shortest street path u->v on one network; returns segment ids or None"""
    ok = allowed[net]
    tx, ty = JXY[v]
    dist = {u: 0.0}
    prev = {}
    h0 = math.hypot(JXY[u][0] - tx, JXY[u][1] - ty)
    pq_ = [(h0, 0.0, u)]
    while pq_:
        f, g, n = heapq.heappop(pq_)
        if n == v:
            path = []
            while n != u:
                n, e = prev[n]
                path.append(e)
            return tuple(path)
        if g > dist.get(n, 1e18) or f > bound:
            continue
        for m, e in adj[n]:
            if not ok[e]:
                continue
            g2 = g + seglen[e]
            if g2 < dist.get(m, 1e18):
                dist[m] = g2
                prev[m] = (n, e)
                heapq.heappush(pq_, (g2 + math.hypot(JXY[m][0] - tx, JXY[m][1] - ty), g2, m))
    return None


cache = {}

# ---------- accumulators ----------
day_all = np.zeros(NE, np.int64)
day_pl = np.zeros(NE, np.int64)
day_dim = {d: np.zeros(NE * len(v), np.int64) for d, v in DIMS.items()}
tc_keys, tc_cnts = [], []
len_total = len_short_hit = len_chord = len_fb_hit = 0.0
n_long = n_chord_ok = 0


def idx_of(values, vocab, fallback):
    lut = {v: i for i, v in enumerate(vocab)}
    fb = lut[fallback]
    return np.fromiter((lut.get(v, fb) for v in values), np.int64, len(values))


def merge_time():
    global tc_keys, tc_cnts
    k = np.concatenate(tc_keys); c = np.concatenate(tc_cnts)
    o = np.argsort(k, kind="stable"); k, c = k[o], c[o]
    uk, s_ = np.unique(k, return_index=True)
    tc_keys, tc_cnts = [uk], [np.add.reduceat(c, s_)]


def sample_pairs(p, x, y, cin, tot_trip, trip_v, t0, t1):
    """sampling snap for pairs p; returns (trip, edge, bin, hit-length)"""
    sdx, sdy = x[p + 1] - x[p], y[p + 1] - y[p]
    sL = np.hypot(sdx, sdy)
    sn = np.maximum(1, np.ceil(sL / SAMPLE_M).astype(np.int64))
    r = np.repeat(np.arange(len(p)), sn)
    k = np.arange(len(r)) - np.repeat(np.cumsum(sn) - sn, sn)
    f = (k + 0.5) / sn[r]
    sx = x[p][r] + f * sdx[r]; sy = y[p][r] + f * sdy[r]
    tid = trip_v[p][r]
    sd = cin[p][r] + f * sL[r]
    ratio = np.where(tot_trip[tid] > 0, sd / np.maximum(tot_trip[tid], 1e-9), 0)
    tb = np.clip(np.floor((t0[tid] + ratio * (t1[tid] - t0[tid])) / BIN_S).astype(np.int64)
                 - (H0 * 3600) // BIN_S, 0, NB - 1)
    _, ii = tree.query(np.column_stack([sx, sy]), distance_upper_bound=SNAP_M, workers=-1)
    hit = ii < NP
    return tid[hit], PE[ii[hit]], tb[hit], float((sL[r] / sn[r])[hit].sum())


pf = pq.ParquetFile(TRIPS)
cols = ["lon", "lat", "t_start", "t_end", "mode", "match", "n_pts",
        "plausible", "purpose_to", "age_band", "sex", "status"]
base = 0
for bi, b in enumerate(pf.iter_batches(batch_size=25000, columns=cols)):
    n = b.num_rows
    lon_b, lat_b = b.column("lon"), b.column("lat")
    offb = np.asarray(lon_b.offsets)
    npts = np.diff(offb)
    match = np.asarray(b.column("match").to_pylist(), dtype=object)
    keep = (match == "n/a") & (npts > 2)
    if not keep.any():
        base += n
        continue
    modes_raw = b.column("mode").to_pylist()
    tnet = np.array([NETS.index(NET_OF_MODE.get(m, "all")) for m in modes_raw])
    tmode = idx_of([m if m in MODES else "Other" for m in modes_raw], MODES, "Other")
    tpl = np.asarray(b.column("plausible").to_pylist(), dtype=bool)
    tdim = {
        "mode": tmode,
        "purpose": idx_of(b.column("purpose_to").to_pylist(), PURPOSES, "Other"),
        "age": idx_of([str(v) for v in b.column("age_band").to_pylist()], AGES, "Unknown"),
        "sex": idx_of([str(v) for v in b.column("sex").to_pylist()], SEXES, "Unknown"),
        "status": idx_of([str(v) for v in b.column("status").to_pylist()], STATUS, "Other/Unknown"),
    }
    t0 = np.asarray(b.column("t_start")); t1 = np.asarray(b.column("t_end"))

    vmask = np.repeat(keep, npts)
    trip_v = np.repeat(np.arange(n), npts)[vmask]
    # a batch can be a slice of a larger buffer: take only its own range
    flo = np.asarray(lon_b.values)[offb[0]:offb[-1]]
    fla = np.asarray(lat_b.values)[offb[0]:offb[-1]]
    x, y = tf.transform(flo[vmask], fla[vmask])
    nvb = len(x)
    samev = trip_v[1:] == trip_v[:-1]
    seg = np.zeros(nvb)
    seg[1:] = np.where(samev, np.hypot(np.diff(x), np.diff(y)), 0.0)
    cum = np.cumsum(seg)
    first = np.maximum.accumulate(np.where(np.r_[True, ~samev], np.arange(nvb), 0))
    cin = cum - cum[first]
    last_flag = np.r_[~samev, True]
    tot_trip = np.zeros(n); tot_trip[trip_v[last_flag]] = cin[last_flag]

    p = np.flatnonzero(samev)
    pL = np.hypot(x[p + 1] - x[p], y[p + 1] - y[p])
    len_total += float(pL.sum())
    short, long_ = p[pL <= SHORT_M], p[pL > SHORT_M]

    parts = []                                   # (trip, edge, bin)
    tr_s, ed_s, bn_s, hitlen = sample_pairs(short, x, y, cin, tot_trip, trip_v, t0, t1)
    parts.append((tr_s, ed_s, bn_s)); len_short_hit += hitlen

    # long chords: junction-to-junction street paths
    if len(long_):
        da, ja = jtree.query(np.column_stack([x[long_], y[long_]]))
        db, jb = jtree.query(np.column_stack([x[long_ + 1], y[long_ + 1]]))
        both = (da <= JUNC_M) & (db <= JUNC_M) & (ja != jb)
        lL = np.hypot(x[long_ + 1] - x[long_], y[long_ + 1] - y[long_])
        mid_d = cin[long_] + lL / 2
        ttr = trip_v[long_]
        ratio = np.where(tot_trip[ttr] > 0, mid_d / np.maximum(tot_trip[ttr], 1e-9), 0)
        lbin = np.clip(np.floor((t0[ttr] + ratio * (t1[ttr] - t0[ttr])) / BIN_S).astype(np.int64)
                       - (H0 * 3600) // BIN_S, 0, NB - 1)
        ok_pairs = np.zeros(len(long_), bool)
        tr_l, ed_l, bn_l = [], [], []
        for q in np.flatnonzero(both):
            net = NETS[tnet[ttr[q]]]
            kkey = (net, int(ja[q]), int(jb[q]))
            path = cache.get(kkey, 0)
            if path == 0:
                path = astar(int(ja[q]), int(jb[q]), net, 1.6 * lL[q] + 60)
                cache[kkey] = path
            if path:
                ok_pairs[q] = True
                tr_l.extend([ttr[q]] * len(path)); ed_l.extend(path)
                bn_l.extend([lbin[q]] * len(path))
        n_long += len(long_); n_chord_ok += int(ok_pairs.sum())
        len_chord += float(lL[ok_pairs].sum())
        if tr_l:
            parts.append((np.asarray(tr_l, np.int64), np.asarray(ed_l, np.int64),
                          np.asarray(bn_l, np.int64)))
        fb = long_[~ok_pairs]
        if len(fb):
            tr_f, ed_f, bn_f, hl = sample_pairs(fb, x, y, cin, tot_trip, trip_v, t0, t1)
            parts.append((tr_f, ed_f, bn_f)); len_fb_hit += hl

    tid = np.concatenate([q[0] for q in parts])
    edge = np.concatenate([q[1] for q in parts])
    tbin = np.concatenate([q[2] for q in parts])

    k3 = np.unique((tid.astype(np.int64) * NE + edge) * NB + tbin)
    tr3 = k3 // (NE * NB); ed3 = (k3 // NB) % NE; bn3 = k3 % NB
    pl3 = tpl[tr3]
    tkey = (ed3[pl3] * len(MODES) + tmode[tr3[pl3]]) * NB + bn3[pl3]
    uk, uc = np.unique(tkey, return_counts=True)
    tc_keys.append(uk); tc_cnts.append(uc.astype(np.int64))

    k2 = np.unique(tr3 * NE + ed3)
    tr2, ed2 = k2 // NE, k2 % NE
    day_all += np.bincount(ed2, minlength=NE)
    pm = tpl[tr2]
    day_pl += np.bincount(ed2[pm], minlength=NE)
    for dname, vocab in DIMS.items():
        day_dim[dname] += np.bincount(ed2[pm] * len(vocab) + tdim[dname][tr2[pm]],
                                      minlength=NE * len(vocab))
    base += n
    if (bi + 1) % 8 == 0:
        merge_time()
    cov = 100 * (len_short_hit + len_chord + len_fb_hit) / max(len_total, 1)
    print(f"  {base:,} trips | route length assigned {cov:.1f}% | chords matched "
          f"{100*n_chord_ok/max(n_long,1):.1f}% | cache {len(cache):,}", flush=True)

merge_time()

day = {"edge_id": np.arange(NE), "trips_all": day_all, "trips": day_pl}
for dname, vocab in DIMS.items():
    m = day_dim[dname].reshape(NE, len(vocab))
    for j, v in enumerate(vocab):
        day[f"{dname}:{v}"] = m[:, j]
dday = pd.DataFrame(day)
dday = dday[dday.trips_all > 0]
pq.write_table(pa.Table.from_pandas(dday, preserve_index=False), OUT_DAY, compression="zstd")
K, C = tc_keys[0], tc_cnts[0]
tdf = pd.DataFrame({"edge_id": K // (len(MODES) * NB), "mode": (K // NB) % len(MODES),
                    "bin": K % NB, "trips": C})
pq.write_table(pa.Table.from_pandas(tdf, preserve_index=False), OUT_TIME, compression="zstd")

cov = 100 * (len_short_hit + len_chord + len_fb_hit) / len_total
print(f"\nroute length assigned to streets: {cov:.2f}%  "
      f"(short snaps {100*len_short_hit/len_total:.1f}%, chord paths "
      f"{100*len_chord/len_total:.1f}%, fallback {100*len_fb_hit/len_total:.1f}%)")
print(f"long chords matched to a street path: {100*n_chord_ok/max(n_long,1):.1f}% of {n_long:,}")
print(f"street segments carrying trips: {len(dday):,}/{NE:,}")
print(f"busiest segment: {int(dday.trips.max()):,} plausible trips/day")
print(f"time cube rows: {len(tdf):,}")
json.dump({"snap_pct": round(cov, 1), "chord_pct": round(100*n_chord_ok/max(n_long,1), 1),
           "segments_with_flow": int(len(dday)), "segments": int(NE),
           "peak_day": int(dday.trips.max())},
          open(os.path.join(DER, "street_flows_stats.json"), "w"), indent=1)
