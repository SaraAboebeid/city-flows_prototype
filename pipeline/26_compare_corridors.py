"""Compare synthetic and phone-based traffic corridor by corridor.

Segment by segment the two sources barely agree (Spearman 0.06 on the 7,232
well-observed roads, stage 22). Both sides are noisy there: the median phone
road carries 2-3 sampled crossings, and one routing choice moves a synthetic
trip to a parallel street. Aggregating to corridors - all segments sharing an
OSM street name - cancels much of that noise, so what is left is the
city-scale pattern.

Compared quantities, per corridor:
  synthetic   length-weighted mean CAR trips per day  (stage 12, 2019 residents)
  phone       length-weighted mean sampled crossings  (stage 21, FlowSense 2024)
  counts      mean ADT of the 2023 count sites on it  (the neutral yardstick)

Length-weighting (sum(flow * length) / sum(length)) makes this "how much
traffic along this corridor", not "how many segments it has". Shares are of
the city total of flow * length, so the two sources can be compared despite
having no common unit: the phones are a 100,000-crossing sample, never
vehicles per day.

Writes corridor_compare.json (statistics + the top corridors) and
       corridors.csv (every corridor, for inspection in Excel or QGIS).
"""
import os, sys, json
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
MIN_LEN_M = 400           # a corridor shorter than this is a side street, not a route
MIN_CROSS = 20            # sampled crossings before a corridor's phone mean is trusted
DRIVE_EXCL = {"footway", "path", "cycleway", "pedestrian", "steps", "track",
              "bridleway", "corridor", "platform", "elevator", "escalator",
              "construction", "proposed", "busway", "bus_guideway"}

to3006 = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)

# ---------- synthetic car volume on drivable, named OSM segments ----------
st = pq.read_table(os.path.join(DER, "streets.parquet"),
                   columns=["edge_id", "highway", "name", "length_m", "lon", "lat"])
day = pq.read_table(os.path.join(DER, "street_flows_day.parquet"),
                    columns=["edge_id", "mode:Car"]).to_pandas()
n_edges = st.num_rows
car = np.zeros(n_edges)
car[day.edge_id.values] = day["mode:Car"].values
hwy = np.asarray(st.column("highway").to_pylist(), dtype=object)
name = pd.Series(st.column("name").to_pylist(), dtype="object").fillna("").str.strip()
elen = np.asarray(st.column("length_m").to_pylist(), float)
drivable = np.array([h not in DRIVE_EXCL for h in hwy])
named = drivable & (name.values != "")
print(f"OSM segments: {n_edges:,} | drivable: {drivable.sum():,} | named: {named.sum():,}", flush=True)

# KD tree of points every ~2 m along the drivable segments (as in stage 22)
lo = st.column("lon").combine_chunks(); la = st.column("lat").combine_chunks()
off = np.asarray(lo.offsets)
X, Y = to3006.transform(np.asarray(lo.values), np.asarray(la.values))
own = np.repeat(np.arange(n_edges), np.diff(off))
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

# corridor = OSM street name; the synthetic side aggregates directly over its segments
syn = pd.DataFrame({"corridor": name.values[named], "len_m": elen[named],
                    "car": car[named]})
syn["vkm"] = syn.car * syn.len_m / 1000
SYN = syn.groupby("corridor").agg(osm_len_km=("len_m", lambda s: s.sum() / 1000),
                                  syn_vkm=("vkm", "sum"),
                                  n_seg=("len_m", "size"))
SYN["syn_mean"] = syn.groupby("corridor").apply(
    lambda g: float((g.car * g.len_m).sum() / g.len_m.sum()), include_groups=False)

# ---------- the phone segments, snapped onto the same corridors ----------
fs = gpd.read_parquet(os.path.join(DER, "flowsense_gbg.parquet"))
print(f"phone segments: {len(fs):,}", flush=True)


def sample_points(geoms, step=STEP_M):
    """Points every `step` m along each geometry, with an owner index."""
    pts, owner = [], []
    for j, g in enumerate(geoms):
        m = max(3, int(g.length // step))
        pts.append(np.array([(p.x, p.y) for p in
                             (g.interpolate((i + 0.5) / m, normalized=True) for i in range(m))]))
        owner.append(np.full(m, j))
    return np.vstack(pts), np.concatenate(owner)


pts, owner = sample_points(fs.geometry)
d, idx = osm_tree.query(pts, distance_upper_bound=SNAP_M)
hit = idx < len(osm_edge)
print(f"phone sample points: {len(pts):,} | snapped within {SNAP_M:.0f} m: {100*hit.mean():.1f}%", flush=True)

# each phone segment takes the street name it snapped to most often
h = pd.DataFrame({"seg": owner[hit], "corridor": name.values[osm_edge[idx[hit]]]})
h = h[h.corridor != ""]
votes = h.groupby(["seg", "corridor"]).size().rename("v").reset_index()
best = votes.sort_values("v").drop_duplicates("seg", keep="last").set_index("seg")
share = best.v / pd.Series(np.bincount(owner, minlength=len(fs)), name="tot").reindex(best.index)
best = best[share >= 0.5]                       # at least half the segment on that street
fs_c = fs.assign(corridor=pd.Series(best.corridor, index=best.index).reindex(range(len(fs))))
fs_c["len_m"] = fs.geometry.length
ph = fs_c.dropna(subset=["corridor"])
print(f"phone segments assigned to a named corridor: {len(ph):,} "
      f"({100*len(ph)/len(fs):.1f}%)", flush=True)

PH = ph.groupby("corridor").agg(phone_len_km=("len_m", lambda s: s.sum() / 1000),
                                cross_all=("obs_all", "sum"), cross_20=("obs_20", "sum"))
for col, out in [("obs_all", "phone_mean"), ("obs_20", "phone20_mean")]:
    PH[out] = ph.groupby("corridor").apply(
        lambda g, c=col: float((g[c] * g.len_m).sum() / g.len_m.sum()), include_groups=False)

# ---------- 2023 traffic counts, onto the same corridors ----------
gt = gpd.read_parquet(os.path.join(DER, "groundtruth_gbg.parquet"))
gt["is_point"] = gt.geom_type == "Point"


def corridor_of(geom, point):
    if point:
        j = osm_tree.query_ball_point((geom.x, geom.y), POINT_M)
        if not j:
            return None
        cand = [(car[e], name.values[e]) for e in np.unique(osm_edge[j]) if name.values[e]]
        return max(cand)[1] if cand else None       # a count sits on the main road
    p, _ = sample_points([geom])
    dd, ii = osm_tree.query(p, distance_upper_bound=SNAP_M)
    ok = ii < len(osm_edge)
    if ok.mean() < 0.5:
        return None
    nm = pd.Series(name.values[osm_edge[ii[ok]]])
    nm = nm[nm != ""]
    return nm.value_counts().idxmax() if len(nm) else None


gt["corridor"] = [corridor_of(g, p) for g, p in zip(gt.geometry, gt.is_point)]
GT = gt.dropna(subset=["corridor"]).groupby("corridor").agg(
    adt_mean=("adt", "mean"), n_counts=("adt", "size"))
print(f"count sites placed on a named corridor: {int(gt.corridor.notna().sum())} of {len(gt)}", flush=True)

# ---------- the corridor table ----------
C = SYN.join(PH, how="inner").join(GT, how="left").reset_index()
C = C[C.osm_len_km * 1000 >= MIN_LEN_M].copy()
C["phone_vkm"] = C.phone_mean * C.phone_len_km
C["phone20_vkm"] = C.phone20_mean * C.phone_len_km
for a, b in [("syn_vkm", "syn_share"), ("phone_vkm", "phone_share"), ("phone20_vkm", "phone20_share")]:
    C[b] = 1000 * C[a] / C[a].sum()             # per mille of the city total
C["log2_ratio"] = np.log2(np.maximum(C.syn_share, 1e-6) / np.maximum(C.phone20_share, 1e-6))
C = C.sort_values("phone20_share", ascending=False)
C.to_csv(os.path.join(DER, "corridors.csv"), index=False, encoding="utf-8-sig",
         float_format="%.4f")


def corr(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < 8:
        return {"n": int(len(a))}
    return {"n": int(len(a)), "spearman": round(float(spearmanr(a, b).statistic), 3),
            "pearson_log": round(float(pearsonr(np.log1p(a), np.log1p(b)).statistic), 3)}


rel = C[C.cross_20 >= MIN_CROSS]
with_counts = C.dropna(subset=["adt_mean"])
rel_counts = rel.dropna(subset=["adt_mean"])
stats = {
    "corridors": int(len(C)),
    "well_observed": {"corridors": int(len(rel)), "min_crossings": MIN_CROSS,
                      "min_length_m": MIN_LEN_M},
    "corridor_level": {
        "synthetic_vs_phone20": corr(rel.syn_mean, rel.phone20_mean),
        "synthetic_vs_phone_all": corr(rel.syn_mean, rel.phone_mean),
        "synthetic_vs_counts": corr(with_counts.syn_mean, with_counts.adt_mean),
        "phone20_vs_counts": corr(with_counts.phone20_mean, with_counts.adt_mean),
        "phone20_vs_counts_well_observed": corr(rel_counts.phone20_mean, rel_counts.adt_mean),
    },
}
seg = os.path.join(DER, "phone_compare.json")
if os.path.exists(seg):
    s = json.load(open(seg, encoding="utf-8"))
    stats["segment_level_for_reference"] = {
        "synthetic_vs_phone20": s.get("syn_vs_phone20_reliable"),
        "synthetic_vs_phone_all": s.get("syn_vs_phone_reliable"),
        "synthetic_vs_counts": s["ground_truth"]["all counts"]["synthetic_vs_counts"],
        "phone20_vs_counts": s["ground_truth"]["all counts"]["phone20_vs_counts"],
    }
top = rel.head(40)
stats["top_corridors_by_phone"] = [
    {"corridor": r.corridor, "km": round(r.osm_len_km, 1),
     "syn_car_per_day": round(r.syn_mean), "phone20_crossings": round(r.phone20_mean, 1),
     "syn_share": round(r.syn_share, 2), "phone20_share": round(r.phone20_share, 2),
     "log2_ratio": round(r.log2_ratio, 2),
     "counts_adt": None if not np.isfinite(r.adt_mean) else round(r.adt_mean)}
    for r in top.itertuples()]
json.dump(stats, open(os.path.join(DER, "corridor_compare.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# ---------- report ----------
print(f"\ncorridors compared: {len(C):,} | well observed (>= {MIN_CROSS} crossings): {len(rel):,}")
print("\nrank agreement (Spearman)")
for k, v in stats["corridor_level"].items():
    ref = stats.get("segment_level_for_reference", {}).get(k)
    r = f"   (segment level: {ref['spearman']})" if ref and "spearman" in ref else ""
    print(f"  {k:34s} n={v.get('n',0):5d}  rho={v.get('spearman','-')}{r}")
print(f"\ntop 25 corridors by phone traffic  (share = per mille of the city; "
      f"ratio = log2 synthetic/phone, + means the model over-loads it)")
print(f"{'corridor':32s}{'km':>6}{'syn/day':>9}{'phone':>8}{'syn%o':>7}{'ph%o':>7}{'ratio':>7}{'ADT2023':>9}")
for r in rel.head(25).itertuples():
    adt = "" if not np.isfinite(r.adt_mean) else f"{r.adt_mean:9,.0f}"
    print(f"{r.corridor[:31]:32s}{r.osm_len_km:6.1f}{r.syn_mean:9,.0f}{r.phone20_mean:8.1f}"
          f"{r.syn_share:7.2f}{r.phone20_share:7.2f}{r.log2_ratio:+7.1f}{adt}")
print(f"\nwrote corridor_compare.json and corridors.csv -> {DER}")
