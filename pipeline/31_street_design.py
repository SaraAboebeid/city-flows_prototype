"""Street size and street design against what the phones saw.

Two questions the phone data cannot answer alone:

  Does traffic match the size of the street?
      OpenStreetMap tags a width in metres on only 2% of drivable roads, but a
      LANE COUNT on 71% of main roads - and main roads are exactly where the
      phone sample is thick enough to trust. Crossings per lane says which
      streets work hardest for their size.

  Do streets built for slower movement actually carry slower traffic?
      The slow-traffic index (stage 28) against cycle lanes, sidewalks,
      on-street parking and the speed limit. Correlation only: the index cannot
      tell a cyclist from a car queuing in traffic.

Tags come from the Overpass tiles stage 11 already cached, which kept every
tag, so nothing is downloaded here. They are joined to our street segments by
OSM way id, and each phone road takes the tags of the segment it snaps to.

Writes flowsense_street_design.parquet and street_design.json (the statistics).
"""
import os, sys, json, glob, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DER  # noqa: E402

import numpy as np
import pandas as pd
import geopandas as gpd
import pyarrow.parquet as pq
from scipy.spatial import cKDTree
from scipy.stats import spearmanr
from pyproj import Transformer

SNAP_M, STEP_M = 8.0, 10.0
RELIABLE = 5
DRIVE_EXCL = {"footway", "path", "cycleway", "pedestrian", "steps", "track",
              "bridleway", "corridor", "platform", "elevator", "escalator",
              "construction", "proposed", "busway", "bus_guideway"}
NO = {"no", "none", "separate"}

# ---------- tags from the Overpass cache ----------
def num(v):
    m = re.search(r"\d+(\.\d+)?", str(v or ""))
    return float(m.group()) if m else np.nan


tags = {}
for f in glob.glob(os.path.join(DER, "osm_streets", "*.json")):
    j = json.load(open(f, encoding="utf-8"))
    for w in (j.get("elements", []) if isinstance(j, dict) else j):
        t = w.get("tags", {})
        if not t.get("highway"):
            continue
        tags[int(w["id"])] = {
            "lanes": num(t.get("lanes")),
            "width": num(t.get("width")),
            "cycle": any(k.startswith("cycleway") and str(v).lower() not in NO for k, v in t.items())
                     or t.get("bicycle") == "designated",
            "walk": (str(t.get("sidewalk", "no")).lower() not in NO)
                    or t.get("foot") in ("designated", "yes"),
            "parking": any(k.startswith("parking:") and str(v).lower() not in NO for k, v in t.items()),
            "oneway": t.get("oneway") == "yes",
        }
print(f"OSM ways with tags: {len(tags):,}", flush=True)

# ---------- our street segments, with those tags ----------
st = pq.read_table(os.path.join(DER, "streets.parquet"),
                   columns=["way_id", "highway", "name", "lon", "lat"])
n_seg = st.num_rows
way = np.asarray(st.column("way_id").to_pylist(), dtype=np.int64)
hwy = np.asarray(st.column("highway").to_pylist(), dtype=object)
nm = pd.Series(st.column("name").to_pylist(), dtype="object").fillna("").values
drivable = np.array([h not in DRIVE_EXCL for h in hwy])
blank = {"lanes": np.nan, "width": np.nan, "cycle": False, "walk": False, "parking": False, "oneway": False}
rows = [tags.get(w, blank) for w in way]
SEG = pd.DataFrame(rows)
SEG["highway"] = hwy
SEG["name"] = nm
# a one-way segment's lane count is its own; a two-way street's lanes are shared
SEG["lanes_eff"] = np.where(SEG.oneway, SEG.lanes, SEG.lanes)
print(f"street segments: {n_seg:,} | drivable {int(drivable.sum()):,} | "
      f"with a lane count {int(SEG.lanes[drivable].notna().sum()):,}", flush=True)

# ---------- KD tree of the drivable segments ----------
to3006 = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)
lo = st.column("lon").combine_chunks(); la = st.column("lat").combine_chunks()
off = np.asarray(lo.offsets)
X, Y = to3006.transform(np.asarray(lo.values), np.asarray(la.values))
own = np.repeat(np.arange(n_seg), np.diff(off))
same = (own[1:] == own[:-1]) & drivable[own[:-1]]
i0 = np.flatnonzero(same)
dx, dy = X[i0 + 1] - X[i0], Y[i0 + 1] - Y[i0]
n = np.maximum(1, np.ceil(np.hypot(dx, dy) / 2).astype(int)) + 1
r = np.repeat(np.arange(len(i0)), n)
k = np.arange(len(r)) - np.repeat(np.cumsum(n) - n, n)
f = k / (n[r] - 1)
tree = cKDTree(np.column_stack([X[i0][r] + f * dx[r], Y[i0][r] + f * dy[r]]))
seg_of = own[i0][r]
print(f"KD points: {len(seg_of):,}", flush=True)

# ---------- snap every phone road to a street segment ----------
R = gpd.read_parquet(os.path.join(DER, "flowsense_sweep_roads.parquet"))
pts, owner = [], []
for j, g in enumerate(R.geometry):
    m = max(3, int(g.length // STEP_M))
    pts.append(np.array([(p.x, p.y) for p in
                         (g.interpolate((i + 0.5) / m, normalized=True) for i in range(m))]))
    owner.append(np.full(m, j))
pts = np.vstack(pts); owner = np.concatenate(owner)
_, idx = tree.query(pts, distance_upper_bound=SNAP_M)
hit = idx < len(seg_of)
h = pd.DataFrame({"road": owner[hit], "seg": seg_of[idx[hit]]})
best = (h.groupby(["road", "seg"]).size().rename("v").reset_index()
          .sort_values("v").drop_duplicates("road", keep="last").set_index("road"))
share = best.v / pd.Series(np.bincount(owner, minlength=len(R))).reindex(best.index)
best = best[share >= 0.5]
print(f"phone roads matched to a street: {len(best):,} of {len(R):,} "
      f"({100*len(best)/len(R):.0f}%)", flush=True)

R = R.reset_index(drop=True)
for col in ["lanes", "width", "cycle", "walk", "parking", "highway", "name"]:
    R[col] = pd.Series(SEG[col].to_numpy()[best.seg.to_numpy()], index=best.index).reindex(R.index)
R["lanes"] = pd.to_numeric(R.lanes, errors="coerce")
R.loc[R.lanes < 1, "lanes"] = np.nan
R["per_lane"] = np.where(R.lanes.notna() & (R.c8 >= RELIABLE), R.c8 / R.lanes, np.nan)
R.to_parquet(os.path.join(DER, "flowsense_street_design.parquet"))

# ---------- what it says ----------
out = {}
busy = R[(R.c8 >= RELIABLE) & R.lanes.notna()]
print(f"\ntraffic per lane, on the {len(busy):,} well-observed roads with a lane count:")
by_lane = {}
for L, g in busy.groupby(busy.lanes.clip(1, 6).astype(int)):
    if len(g) >= 30:
        by_lane[int(L)] = {"roads": int(len(g)), "median_crossings": round(float(g.c8.median()), 1),
                           "median_per_lane": round(float(g.per_lane.median()), 1)}
        print(f"  {int(L)} lane(s): n={len(g):5,}  median {g.c8.median():6.1f} crossings"
              f"  =  {g.per_lane.median():5.1f} per lane")
out["by_lanes"] = by_lane
rho = spearmanr(busy.lanes, busy.c8).statistic
out["lanes_vs_traffic_spearman"] = round(float(rho), 3)
print(f"  lane count vs traffic: Spearman {rho:.3f}")

by_class = {}
for h_, g in busy.groupby(busy.highway):
    if len(g) >= 30:
        by_class[str(h_)] = {"roads": int(len(g)), "median_lanes": float(g.lanes.median()),
                             "median_per_lane": round(float(g.per_lane.median()), 1)}
out["by_class"] = by_class
print("\n  by street class (median crossings per lane):")
for h_, v in sorted(by_class.items(), key=lambda kv: -kv[1]["median_per_lane"]):
    print(f"    {h_:14s} n={v['roads']:5,}  {v['median_per_lane']:6.1f}")

# slow traffic against the street it runs on
slow = R[R.slow_index.notna() & (R.c0 >= RELIABLE)]
out["slow_by_class"] = {}
print(f"\nslow-traffic index by street class ({len(slow):,} roads):")
for h_, g in slow.groupby(slow.highway):
    if len(g) >= 50:
        out["slow_by_class"][str(h_)] = {"roads": int(len(g)),
                                         "median_slow_index": round(float(g.slow_index.median()), 2)}
for h_, v in sorted(out["slow_by_class"].items(), key=lambda kv: -kv[1]["median_slow_index"]):
    print(f"  {h_:14s} n={v['roads']:5,}  median index {v['median_slow_index']:5.2f}")
out["slow_by_lanes"] = {}
sl = slow[slow.lanes.notna()]
for L, g in sl.groupby(sl.lanes.clip(1, 6).astype(int)):
    if len(g) >= 30:
        out["slow_by_lanes"][int(L)] = {"roads": int(len(g)),
                                        "median_slow_index": round(float(g.slow_index.median()), 2)}

# Why there is no cycle-infrastructure comparison here: Göteborg maps its cycle
# network as SEPARATE ways (highway=cycleway/path), and FlowSense's network is
# Trafikverket's road network, which does not contain them. On the road ways
# themselves a cycleway tag is common but almost always says "no".
cov = {}
for label, mask in [("cycle", R.cycle == True), ("sidewalk", R.walk == True), ("parking", R.parking == True)]:
    g = R[(R.c0 >= RELIABLE)]
    cov[label] = {"roads_with": int(mask[g.index].sum()), "of": int(len(g))}
    print(f"\n  {label} infrastructure on well-observed roads: {cov[label]['roads_with']} of {cov[label]['of']}"
          f" - too few to compare" if cov[label]["roads_with"] < 200 else "")
out["design_coverage"] = cov
out["slow_by_limit"] = {str(int(sp)): round(float(g.slow_index.median()), 2)
                        for sp, g in slow.groupby(slow.ms.fillna(-1)) if sp > 0 and len(g) >= 100}
out["matched"] = {"roads": int(len(R)), "with_street": int(len(best)),
                  "with_lanes": int(R.lanes.notna().sum()), "reliable_with_lanes": int(len(busy))}
json.dump(out, open(os.path.join(DER, "street_design.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"\nwrote flowsense_street_design.parquet and street_design.json -> {DER}")
