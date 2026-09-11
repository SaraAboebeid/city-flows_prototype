"""Compare synthetic car flows with FlowSense phone-based vehicle flows and
with 2023 traffic counts (ground truth).

Synthetic side: whole-day plausible CAR trips per OSM street segment (stage 12).
Phone side: FlowSense trajectory counts per NVDB segment (stage 21), a sparse
2024 sample - rank comparisons only, never absolute.

Matching is by geometry: points every 10 m along a NVDB segment (or ground
truth link) snap to the nearest drivable OSM segment within SNAP_M; the value
is the median over the snapped points. Municipal count points take the
busiest drivable segment within POINT_M (a count sits on the main road, not on
the side street next to it).

Writes phone_payload.json (for the page and the JS version) and
       phone_compare.json (all statistics, human-readable).
"""
import os, sys, json, gzip, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DER  # noqa: E402

import numpy as np
import pandas as pd
import geopandas as gpd
import pyarrow.parquet as pq
from scipy.spatial import cKDTree
from scipy.stats import spearmanr, pearsonr
from pyproj import Transformer

SNAP_M, POINT_M, STEP_M = 8.0, 25.0, 10.0
RELIABLE = 5              # phone trajectories needed before a segment is compared
DRIVE_EXCL = {"footway", "path", "cycleway", "pedestrian", "steps", "track",
              "bridleway", "corridor", "platform", "elevator", "escalator",
              "construction", "proposed", "busway", "bus_guideway"}

to3006 = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)
to4326 = Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)

# ---------- synthetic car volume on drivable OSM segments ----------
st = pq.read_table(os.path.join(DER, "streets.parquet"),
                   columns=["edge_id", "highway", "lon", "lat"])
day = pq.read_table(os.path.join(DER, "street_flows_day.parquet"),
                    columns=["edge_id", "mode:Car"]).to_pandas()
car = np.zeros(st.num_rows)
car[day.edge_id.values] = day["mode:Car"].values
hwy = np.asarray(st.column("highway").to_pylist(), dtype=object)
drivable = np.array([h not in DRIVE_EXCL for h in hwy])

lo = st.column("lon").combine_chunks(); la = st.column("lat").combine_chunks()
off = np.asarray(lo.offsets)
X, Y = to3006.transform(np.asarray(lo.values), np.asarray(la.values))
own = np.repeat(np.arange(st.num_rows), np.diff(off))
same = (own[1:] == own[:-1]) & drivable[own[:-1]]
i0 = np.flatnonzero(same)
dx, dy = X[i0 + 1] - X[i0], Y[i0 + 1] - Y[i0]
n = np.maximum(1, np.ceil(np.hypot(dx, dy) / 2).astype(int)) + 1
r = np.repeat(np.arange(len(i0)), n)
k = np.arange(len(r)) - np.repeat(np.cumsum(n) - n, n)
f = k / (n[r] - 1)
osm_tree = cKDTree(np.column_stack([X[i0][r] + f * dx[r], Y[i0][r] + f * dy[r]]))
osm_edge = own[i0][r]
print(f"drivable OSM KD points: {len(osm_edge):,}", flush=True)


def sample_line(geom, step=STEP_M):
    L = geom.length
    m = max(3, int(L // step))
    return np.array([(p.x, p.y) for p in (geom.interpolate((j + 0.5) / m, normalized=True)
                                          for j in range(m))])


def syn_on_line(geom):
    pts = sample_line(geom)
    d, i = osm_tree.query(pts, distance_upper_bound=SNAP_M)
    hit = i < len(osm_edge)
    if hit.mean() < 0.5:
        return np.nan
    return float(np.median(car[osm_edge[i[hit]]]))


# ---------- FlowSense segments ----------
fs = gpd.read_parquet(os.path.join(DER, "flowsense_gbg.parquet"))
fs = fs[fs.obs_all > 0].reset_index(drop=True)          # payload: roads the phones saw
fs["syn"] = [syn_on_line(g) for g in fs.geometry]
matched = fs.syn.notna()
print(f"phone-observed segments: {len(fs):,} | matched to OSM streets: {int(matched.sum()):,} "
      f"({100*matched.mean():.1f}%)", flush=True)


def corr(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < 8:
        return {"n": int(len(a))}
    return {"n": int(len(a)), "spearman": round(float(spearmanr(a, b).statistic), 3),
            "pearson_log": round(float(pearsonr(np.log1p(a), np.log1p(b)).statistic), 3)}


stats = {"segments_observed": int(len(fs)), "segments_matched": int(matched.sum()),
         "reliable_threshold": RELIABLE, "phone_trajectories": int(fs.obs_all.sum())}
m = fs[matched]
stats["syn_vs_phone_all"] = corr(m.syn, m.obs_all)
stats["syn_vs_phone_reliable"] = corr(m[m.obs_all >= RELIABLE].syn, m[m.obs_all >= RELIABLE].obs_all)
stats["syn_vs_phone20_reliable"] = corr(m[m.obs_20 >= RELIABLE].syn, m[m.obs_20 >= RELIABLE].obs_20)
# the NVDB network labels every road "unclassified", so break down by speed limit
by = {}
rel_m = m[m.obs_all >= RELIABLE]
for sp, g in rel_m.groupby(rel_m.maxspeed.fillna(-1).astype(int)):
    if sp > 0 and len(g) >= 30:
        by[f"{sp} km/h"] = corr(g.syn, g.obs_all)
stats["by_speed_limit"] = by

# ---------- ground truth ----------
gt = gpd.read_parquet(os.path.join(DER, "groundtruth_gbg.parquet"))
fs_all = gpd.read_parquet(os.path.join(DER, "flowsense_gbg.parquet"))
pts, own_fs = [], []
for j, g in enumerate(fs_all.geometry):
    s = sample_line(g, 10.0)
    pts.append(s); own_fs.append(np.full(len(s), j))
fs_tree = cKDTree(np.vstack(pts)); fs_own = np.concatenate(own_fs)


def phone_on(geom, col, point=False):
    if point:
        idx = fs_tree.query_ball_point((geom.x, geom.y), POINT_M)
        return float(fs_all[col].values[fs_own[idx]].max()) if idx else np.nan
    p = sample_line(geom)
    d, i = fs_tree.query(p, distance_upper_bound=SNAP_M)
    hit = i < len(fs_own)
    return float(np.median(fs_all[col].values[fs_own[i[hit]]])) if hit.mean() >= 0.5 else np.nan


def syn_on_point(pt):
    idx = osm_tree.query_ball_point((pt.x, pt.y), POINT_M)
    return float(car[osm_edge[idx]].max()) if idx else np.nan


gt["is_point"] = gt.geom_type == "Point"
gt["syn"] = [syn_on_point(g) if p else syn_on_line(g) for g, p in zip(gt.geometry, gt.is_point)]
gt["phone"] = [phone_on(g, "obs_all", p) for g, p in zip(gt.geometry, gt.is_point)]
gt["phone20"] = [phone_on(g, "obs_20", p) for g, p in zip(gt.geometry, gt.is_point)]
gt_stats = {}
for name, sub in [("all counts", gt), ("highway links", gt[~gt.is_point]),
                  ("municipal points", gt[gt.is_point])]:
    gt_stats[name] = {"synthetic_vs_counts": corr(sub.syn, sub.adt),
                      "phone_vs_counts": corr(sub.phone, sub.adt),
                      "phone20_vs_counts": corr(sub.phone20, sub.adt)}
stats["ground_truth"] = gt_stats

# why synthetic is weak: scope (residents only) and under-weighted big roads
v = gt.dropna(subset=["syn"])
stats["counts_with_zero_synthetic"] = {"n": int((v.syn == 0).sum()), "of": int(len(v)),
                                       "pct": round(100 * float((v.syn == 0).mean()), 1)}
bands = pd.cut(v.adt, [0, 2000, 5000, 15000, 30000, 1e7],
               labels=["<2k", "2-5k", "5-15k", "15-30k", ">30k"])
stats["synthetic_to_counts_ratio_by_size"] = {
    str(b): round(float((v.syn / v.adt)[bands == b].median()), 2)
    for b in bands.cat.categories if (bands == b).any()}
json.dump(stats, open(os.path.join(DER, "phone_compare.json"), "w"), indent=1)
print(json.dumps(stats, indent=1))

# ---------- payload ----------
def pack(geoms):
    parts, npts = [], []
    for g in geoms:
        g = g.simplify(2.0)
        xs, ys = np.array(g.coords).T
        lo_, la_ = to4326.transform(xs, ys)
        q = np.column_stack([np.round(np.asarray(lo_) * 1e5), np.round(np.asarray(la_) * 1e5)]).astype(np.int64)
        while len(q) > 1:
            bad = np.flatnonzero(np.abs(np.diff(q, axis=0)).max(axis=1) > 30000)
            if bad.size == 0:
                break
            q = np.insert(q, bad + 1, (q[bad] + q[bad + 1]) // 2, axis=0)
        parts += [q[0].astype(np.int32).tobytes(), np.diff(q, axis=0).astype(np.int16).tobytes()]
        npts.append(len(q))
    return b"".join(parts), np.asarray(npts, np.uint16)


blob = lambda b: base64.b64encode(gzip.compress(b if isinstance(b, bytes) else
                                                np.ascontiguousarray(b).tobytes(), 9)).decode()
order = np.argsort(fs.obs_all.values, kind="stable")          # quiet first, busy on top
fs = fs.iloc[order].reset_index(drop=True)
coords, npts = pack(fs.geometry)
rel = (fs.obs_all >= RELIABLE) & fs.syn.notna()
tot_syn = fs.syn[rel].sum(); tot_obs = fs.obs_all[rel].sum()
ratio = np.where(rel, np.log2(np.maximum(fs.syn / max(tot_syn, 1), 1e-9) /
                              np.maximum(fs.obs_all / max(tot_obs, 1), 1e-9)), 0)
hw_vocab = sorted(fs.highway.fillna("unknown").unique())

gpt = gt.copy()
gpt["pt"] = [g if p else g.interpolate(0.5, normalized=True) for g, p in zip(gpt.geometry, gpt.is_point)]
glon, glat = to4326.transform(np.array([p.x for p in gpt.pt]), np.array([p.y for p in gpt.pt]))
ground = [{"lon": round(float(a), 5), "lat": round(float(b), 5), "adt": int(r_.adt),
           "syn": None if not np.isfinite(r_.syn) else round(float(r_.syn)),
           "phone": None if not np.isfinite(r_.phone) else round(float(r_.phone)),
           "src": "highway" if not r_.is_point else "municipal",
           "name": str(r_["name"]) if r_.is_point else ""}
          for a, b, (_, r_) in zip(glon, glat, gpt.iterrows())]

payload = {
    "n": int(len(fs)), "reliable": RELIABLE, "hw_vocab": hw_vocab, "stats": stats,
    "coords": blob(coords), "npts": blob(npts),
    "obs": blob(fs.obs_all.clip(0, 65535).values.astype(np.uint16)),
    "obs20": blob(fs.obs_20.clip(0, 65535).values.astype(np.uint16)),
    "syn": blob(np.nan_to_num(fs.syn.values, nan=-1).astype(np.float32)),
    "ratio": blob(np.clip(np.round(ratio * 32), -127, 127).astype(np.int8)),
    "hw": blob(np.array([hw_vocab.index(h if isinstance(h, str) else "unknown")
                         for h in fs.highway], np.uint8)),
    # signposted speed limit (km/h, 0 = unknown) - picks the time-of-day profile
    "spd": blob(np.nan_to_num(fs.maxspeed.values.astype(float), nan=0).clip(0, 255).astype(np.uint8)),
    "ground": ground,
}
out = os.path.join(DER, "phone_payload.json")
json.dump(payload, open(out, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
print(f"\nwrote {out} ({os.path.getsize(out)/1e6:.2f} MB): {len(fs):,} segments, "
      f"{int(rel.sum()):,} compared (>= {RELIABLE} trajectories), {len(ground)} counts")
