"""Pack the speed sweep, uncertainty and network residual for the phone dashboard.

One payload, replacing the two the dashboard used to read:

  directed roads   geometry + crossings at each of the 9 speed filters, for the
                   moving particles (direction of travel is the geometry's)
  roads            undirected geometry + the same 9 counts, speed class, the
                   slow-traffic index (stage 28) and the network rank
                   difference (stage 29)
  load             the 100 m grid of stage 9, per filter and per speed class,
                   so the time-of-day profiles still apply
  ci               a Poisson 95% interval lookup for counts 0..200, so the page
                   can show the sampling range without a stats library
  ground           the 2023 count sites, and the quality statistics

Writes ../gothenburg-phone-js/data/sweep.json
"""
import os, sys, json, gzip, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DER, PHONEWEB, carto_key  # noqa: E402

import numpy as np
import geopandas as gpd
import pandas as pd
from scipy.stats import chi2
from pyproj import Transformer

TH = [0, 2.5, 5, 7.5, 10, 12.5, 15, 17.5, 20]
C = [f"c{i}" for i in range(len(TH))]
SPEED_CLASSES = [30, 40, 50, 60, 70, 80, 90, 100, 110, 120]
NCL = len(SPEED_CLASSES)
CELL, X0, Y0 = 100.0, 299000.0, 6383900.0              # identical to stages 9 and 23
NX = int(np.ceil(36000 / CELL)) + 1
NY = int(np.ceil(33400 / CELL)) + 1
CI_MAX = 200

OUT = os.path.join(PHONEWEB, "data")
os.makedirs(OUT, exist_ok=True)
to4326 = Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)
blob = lambda b: base64.b64encode(gzip.compress(b if isinstance(b, bytes) else
                                                np.ascontiguousarray(b).tobytes(), 9)).decode()


def speed_class(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return SPEED_CLASSES.index(50)
    return int(np.argmin([abs(v - c) for c in SPEED_CLASSES]))


def pack(geoms):
    """polylines as int32 first vertex + int16 deltas, 1e-5 degrees"""
    parts, npts = [], []
    for g in geoms:
        xs, ys = np.array(g.simplify(2.0).coords).T[:2]
        lo, la = to4326.transform(xs, ys)
        q = np.column_stack([np.round(np.asarray(lo) * 1e5),
                             np.round(np.asarray(la) * 1e5)]).astype(np.int64)
        q = q[np.insert(np.abs(np.diff(q, axis=0)).max(axis=1) > 0, 0, True)]
        if len(q) < 2:
            q = np.vstack([q, q[-1] + 1])
        while True:
            bad = np.flatnonzero(np.abs(np.diff(q, axis=0)).max(axis=1) > 30000)
            if bad.size == 0:
                break
            q = np.insert(q, bad + 1, (q[bad] + q[bad + 1]) // 2, axis=0)
        parts += [q[0].astype(np.int32).tobytes(), np.diff(q, axis=0).astype(np.int16).tobytes()]
        npts.append(len(q))
    return blob(b"".join(parts)), blob(np.asarray(npts, np.uint16))


u16 = lambda a: np.clip(np.asarray(a), 0, 65535).astype(np.uint16)

# ---------- undirected roads ----------
R = gpd.read_parquet(os.path.join(DER, "flowsense_sweep_roads.parquet"))
cen = pd.read_parquet(os.path.join(DER, "flowsense_centrality.parquet"))
R = R.merge(cen, on="pair", how="left")
R["cls"] = [speed_class(v) for v in R.ms]
# street size and class from OpenStreetMap (stage 31)
des_path = os.path.join(DER, "flowsense_street_design.parquet")
if os.path.exists(des_path):
    des = gpd.read_parquet(des_path)[["pair", "lanes", "highway"]].rename(
        columns={"highway": "osm_class"})       # stage 28 already has a "highway" column
    R = R.merge(des, on="pair", how="left")
else:
    R["lanes"] = np.nan; R["osm_class"] = None
STREET_CLASSES = ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
                  "secondary", "secondary_link", "tertiary", "tertiary_link", "residential",
                  "unclassified", "living_street", "service"]
R["scls"] = R.osm_class.map({h: i for i, h in enumerate(STREET_CLASSES)}).fillna(255).astype(int)
R["lanes_u8"] = R.lanes.fillna(0).clip(0, 12).astype(int)     # 0 = not tagged
print(f"roads with a lane count: {int((R.lanes_u8 > 0).sum()):,} of {len(R):,}", flush=True)
print(f"roads: {len(R):,}", flush=True)
rc, rn = pack(R.geometry)

# ---------- directed roads (the particles) ----------
Dd = gpd.read_parquet(os.path.join(DER, "flowsense_sweep.parquet"))
Dd["cls"] = [speed_class(v) for v in Dd.ms]
print(f"directed records: {len(Dd):,}", flush=True)
dc, dn = pack(Dd.geometry)

# ---------- 100 m load grid, per filter and speed class ----------
hits = np.zeros((len(TH), NX * NY), np.int64)
cls_hits = np.zeros((len(TH), NX * NY, NCL), np.int64)
for g, cl, counts in zip(R.geometry, R.cls, R[C].to_numpy()):
    m = max(2, int(g.length // 25) + 1)
    pts = [g.interpolate(t, normalized=True) for t in np.linspace(0, 1, m)]
    ix = np.array([int((p.x - X0) // CELL) for p in pts])
    iy = np.array([int((p.y - Y0) // CELL) for p in pts])
    ok = (ix >= 0) & (ix < NX) & (iy >= 0) & (iy < NY)
    if not ok.any():
        continue
    cells = np.unique(iy[ok] * NX + ix[ok])
    for i, n in enumerate(counts):
        if n:
            hits[i, cells] += n
            cls_hits[i, cells, cl] += n
active = np.flatnonzero(hits.sum(axis=0) > 0)
iy, ix = np.divmod(active, NX)
clon, clat = to4326.transform(X0 + (ix + 0.5) * CELL, Y0 + (iy + 0.5) * CELL)
pos = np.column_stack([np.round(np.asarray(clon) * 1e5), np.round(np.asarray(clat) * 1e5)]).astype(np.int32)
print(f"load cells: {len(active):,}", flush=True)

# ---------- Poisson interval lookup ----------
k = np.arange(CI_MAX + 1)
ci_lo = np.where(k > 0, chi2.ppf(0.025, 2 * np.maximum(k, 1)) / 2, 0.0)
ci_hi = chi2.ppf(0.975, 2 * (k + 1)) / 2

# ---------- count sites and the quality statistics ----------
ph = json.load(open(os.path.join(DER, "phone_payload.json"), encoding="utf-8"))
ground = [{k2: d[k2] for k2 in ("lon", "lat", "adt", "phone", "src", "name")} for d in ph["ground"]]
gt = ph["stats"]["ground_truth"]

out = {
    "thresholds": TH,
    "speed_classes": SPEED_CLASSES,
    "street_classes": STREET_CLASSES,
    "sample_crossings": 100000,
    "roads": {
        "n": int(len(R)), "coords": rc, "npts": rn,
        "cls": blob(R.cls.to_numpy(np.uint8)),
        "counts": [blob(u16(R[c])) for c in C],
        # x100, so an index of 2.5 travels as 250 in a uint16
        "slow": blob(u16(np.nan_to_num(R.slow_index.to_numpy(), nan=0) * 100)),
        "slow_known": blob(R.slow_index.notna().to_numpy(np.uint8)),
        # rank difference in [-1, 1], as int8 x100
        "resid": blob(np.clip(np.nan_to_num(R.residual.to_numpy(), nan=0) * 100, -128, 127).astype(np.int8)),
        "resid_known": blob(R.residual.notna().to_numpy(np.uint8)),
        "lanes": blob(R.lanes_u8.to_numpy(np.uint8)),          # 0 = not tagged in OSM
        "scls": blob(R.scls.to_numpy(np.uint8)),               # index into street_classes, 255 = unknown
    },
    "directed": {
        "n": int(len(Dd)), "coords": dc, "npts": dn,
        "cls": blob(Dd.cls.to_numpy(np.uint8)),
        "counts": [blob(u16(Dd[c])) for c in C],
    },
    "load": {
        "cell_m": CELL, "ncell": int(len(active)), "pos": blob(pos),
        "totals": [blob(u16(hits[i, active])) for i in range(len(TH))],
        "cls": [blob(u16(cls_hits[i, active])) for i in range(len(TH))],
    },
    "ci": {"max": CI_MAX, "lo": blob(ci_lo.astype(np.float32)), "hi": blob(ci_hi.astype(np.float32))},
    "ground": ground,
    "stats": {
        "ground_truth": {g: {k2: v for k2, v in rows.items() if k2.startswith("phone")}
                         for g, rows in gt.items()},
        "roads_total": int(len(R)),
        "roads_thin": int((R.c0 < 5).sum()),
        "median_rse": float(np.nanmedian(R.rse_all)),
        "slow_by_limit": {str(int(sp)): round(float(g.slow_index.median()), 2)
                          for sp, g in R[R.slow_index.notna()].groupby(R.ms.fillna(-1))
                          if sp > 0 and len(g) >= 150},
        "reached": [int((R[c] > 0).sum()) for c in C],
        "roads_with_lanes": int((R.lanes_u8 > 0).sum()),
        **({"design": json.load(open(os.path.join(DER, "street_design.json"), encoding="utf-8"))}
           if os.path.exists(os.path.join(DER, "street_design.json")) else {}),
    },
}
p = os.path.join(OUT, "sweep.json")
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(f"\nwrote sweep.json ({os.path.getsize(p)/1e6:.2f} MB) -> {OUT}")

# the dashboard needs nothing else: sweep.json plus the basemap key
for f in os.listdir(OUT):
    if f != "sweep.json":
        os.remove(os.path.join(OUT, f))
key = carto_key()
json.dump({"cartoApiKey": key}, open(os.path.join(PHONEWEB, "config.json"), "w"), indent=1)
print("basemap key: " + ("written to config.json" if key else
      "MISSING - paste your CARTO key into carto_api_key.txt and re-run"))
