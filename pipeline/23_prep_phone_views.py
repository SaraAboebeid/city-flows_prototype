"""Phone data (FlowSense) for the PHONE FLOWS and PHONE LOAD views.

What FlowSense publishes (see B_estimating_flows/3_relative_flows.ipynb in the
authors' repository): map-matched trips are split into (trip, road) crossings,
100,000 crossings are sampled at random for each filter variant, and each
road's number is how many sampled trips crossed it - per direction of travel.
There is no time of day and no individual trip in the public data.

So this stage keeps:
  directed roads  each direction's own geometry (oriented in travel direction)
                  and count, for ALL SPEEDS and >= 20 KM/H - the moving
                  particles are drawn from these (direction and relative
                  volume are real; timing is illustrative)
  load grid       the same 100 m grid as the synthetic STREET LOAD (stage 9):
                  crossings per cell, whole sample

Writes phone_views.json
"""
import os, sys, json, gzip, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import FLOWSENSE, DER  # noqa: E402

import numpy as np
import pyogrio
from pyproj import Transformer

CELL, X0, Y0 = 100.0, 299000.0, 6383900.0          # identical to stage 9
NX = int(np.ceil(36000 / CELL)) + 1
NY = int(np.ceil(33400 / CELL)) + 1
# speed-limit classes that pick a time-of-day profile (stage 24); cells keep
# their crossings split by class so each class can follow its own profile
SPEED_CLASSES = [30, 40, 50, 60, 70, 80, 90, 100, 110, 120]
NCL = len(SPEED_CLASSES)


def speed_class(v):
    if isinstance(v, (list, tuple, np.ndarray)):
        v = v[0] if len(v) else None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return SPEED_CLASSES.index(50)                 # unknown: typical urban street
    return int(np.argmin([abs(v - c) for c in SPEED_CLASSES]))

to4326 = Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)
fl = pyogrio.read_dataframe(
    os.path.join(FLOWSENSE, r"traffic_flows\traffic_flows\flows_gbg_flows_2024_random1to2.geojson"),
    columns=["maxspeed", "trajcount_minavgspeed0", "trajcount_minavgspeed20"])
fl["cls"] = [speed_class(v) for v in fl.maxspeed]
fl["c_all"] = fl.trajcount_minavgspeed0.astype(int)
fl["c_20"] = fl.trajcount_minavgspeed20.astype(int)
fl = fl[(fl.c_all > 0) | (fl.c_20 > 0)].reset_index(drop=True)
print(f"directed roads with any crossing: {len(fl):,} "
      f"(all speeds {int((fl.c_all>0).sum()):,}, >=20 km/h {int((fl.c_20>0).sum()):,})")

# ---------- directed geometries (travel direction = geometry direction) ----------
parts, npts = [], []
cell_hits = {"all": np.zeros(NX * NY, np.int64), "v20": np.zeros(NX * NY, np.int64)}
cell_cls = {"all": np.zeros((NX * NY, NCL), np.int64), "v20": np.zeros((NX * NY, NCL), np.int64)}
for g, ca, c2, cl in zip(fl.geometry, fl.c_all, fl.c_20, fl.cls):
    xs, ys = np.array(g.simplify(2.0).coords).T[:2]
    lo, la = to4326.transform(xs, ys)
    q = np.column_stack([np.round(np.asarray(lo) * 1e5), np.round(np.asarray(la) * 1e5)]).astype(np.int64)
    while len(q) > 1:
        bad = np.flatnonzero(np.abs(np.diff(q, axis=0)).max(axis=1) > 30000)
        if bad.size == 0:
            break
        q = np.insert(q, bad + 1, (q[bad] + q[bad + 1]) // 2, axis=0)
    parts += [q[0].astype(np.int32).tobytes(), np.diff(q, axis=0).astype(np.int16).tobytes()]
    npts.append(len(q))
    # grid: every 100 m cell the road passes through gets its crossings (once)
    L = g.length
    m = max(2, int(L // 25) + 1)
    pts = [g.interpolate(t, normalized=True) for t in np.linspace(0, 1, m)]
    ix = np.array([int((p.x - X0) // CELL) for p in pts]); iy = np.array([int((p.y - Y0) // CELL) for p in pts])
    ok = (ix >= 0) & (ix < NX) & (iy >= 0) & (iy < NY)
    cells = np.unique(iy[ok] * NX + ix[ok])
    cell_hits["all"][cells] += ca
    cell_hits["v20"][cells] += c2
    cell_cls["all"][cells, cl] += ca
    cell_cls["v20"][cells, cl] += c2

active = np.flatnonzero((cell_hits["all"] > 0) | (cell_hits["v20"] > 0))
iy, ix = np.divmod(active, NX)
clon, clat = to4326.transform(X0 + (ix + 0.5) * CELL, Y0 + (iy + 0.5) * CELL)
pos = np.column_stack([np.round(np.asarray(clon) * 1e5), np.round(np.asarray(clat) * 1e5)]).astype(np.int32)

blob = lambda b: base64.b64encode(gzip.compress(b if isinstance(b, bytes) else
                                                np.ascontiguousarray(b).tobytes(), 9)).decode()
out = {
    "directed": {"n": int(len(fl)), "coords": blob(b"".join(parts)),
                 "npts": blob(np.asarray(npts, np.uint16)),
                 "c_all": blob(fl.c_all.clip(0, 65535).values.astype(np.uint16)),
                 "c_20": blob(fl.c_20.clip(0, 65535).values.astype(np.uint16)),
                 "cls": blob(fl.cls.values.astype(np.uint8))},
    "load": {"cell_m": CELL, "ncell": int(len(active)), "pos": blob(pos),
             "all": blob(np.clip(cell_hits["all"][active], 0, 65535).astype(np.uint16)),
             "v20": blob(np.clip(cell_hits["v20"][active], 0, 65535).astype(np.uint16)),
             # crossings per cell split by speed class (ncell x nclass)
             "cls_all": blob(np.clip(cell_cls["all"][active], 0, 65535).astype(np.uint16)),
             "cls_v20": blob(np.clip(cell_cls["v20"][active], 0, 65535).astype(np.uint16))},
    "speed_classes": SPEED_CLASSES,
    "sample_crossings": 100000,
}
p = os.path.join(DER, "phone_views.json")
json.dump(out, open(p, "w"), separators=(",", ":"))
print(f"load grid: {len(active):,} cells (peak {int(cell_hits['all'].max())} crossings, all speeds)")
print(f"wrote {p} ({os.path.getsize(p)/1e6:.2f} MB)")
