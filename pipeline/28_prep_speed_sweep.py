"""All nine average-speed filters from FlowSense, not just two.

The published file carries a trajectory count per road for every minimum
average speed from 0 to 20 km/h in 2.5 steps. Each one is its own random draw
of 100,000 (trip, road) crossings from the trips that pass that filter - they
are NOT nested subsets, so a road's count can rise as the filter tightens.

What that gives: sweeping the filter upwards moves the map from all movement
(walking and cycling included) to motor traffic only. The spatial pattern
really does change - rank correlation with the all-speeds map falls from 0.72
at 5 km/h to 0.57 at 20 km/h.

Derived here, per road (both directions summed):
  slow index    share at 0 km/h / share at >= 20 km/h. Above 1 = relatively
                more slow traffic than the city average; 50 km/h streets sit
                at 2.5, 80 km/h roads at 0.35
  uncertainty   the counts are a Poisson sample: relative standard error
                1/sqrt(count), and an exact 95% interval

Writes flowsense_sweep.parquet (directed, with geometry) and
       flowsense_sweep_roads.parquet (one row per road, undirected).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import FLOWSENSE, DER  # noqa: E402

import numpy as np
import pandas as pd
import geopandas as gpd
import pyogrio
from scipy.stats import chi2

SRC = os.path.join(FLOWSENSE, r"traffic_flows\traffic_flows\flows_gbg_flows_2024_random1to2.geojson")
NET = os.path.join(FLOWSENSE, r"road_network\road_network\preprocessed\road_network_trafikverket_edges_gbg.geojson")
TH = ["0", "2.5", "5", "7.5", "10", "12.5", "15", "17.5", "20"]
COLS = [f"trajcount_minavgspeed{t}" for t in TH]
first = lambda v: (v[0] if len(v) else None) if isinstance(v, (list, np.ndarray)) else v

fl = pyogrio.read_dataframe(SRC, columns=COLS + ["maxspeed"])
print(f"directed road records: {len(fl):,}", flush=True)
# the network file aligns row by row with the flows file (as in stage 21), and
# carries the u/v/key that identify an undirected segment
net = pyogrio.read_dataframe(NET, columns=["u", "v", "key", "highway", "length"],
                             read_geometry=False)
assert len(net) == len(fl), "flows and network are expected to align row by row"
fl = fl.join(net)
a, b = fl.u.astype(np.int64).values, fl.v.astype(np.int64).values
fl["pair"] = [f"{min(x, y)}-{max(x, y)}-{k}" for x, y, k in zip(a, b, fl.key.astype(int))]
fl["ms"] = pd.to_numeric(fl.maxspeed.map(first), errors="coerce")
for i, t in enumerate(TH):
    fl[f"c{i}"] = fl[COLS[i]].fillna(0).astype(np.int32)
C = [f"c{i}" for i in range(len(TH))]
fl = fl[["pair", "ms", "highway", "length", "geometry"] + C]
keep = fl[C].to_numpy().sum(axis=1) > 0
fl = fl[keep].reset_index(drop=True)
print(f"directed records with any crossing at any filter: {len(fl):,}", flush=True)
fl.to_parquet(os.path.join(DER, "flowsense_sweep.parquet"))

# ---------- one row per undirected segment (the unit the rest of the pipeline uses) ----------
agg = fl.groupby("pair")[C].sum()
agg["ms"] = fl.groupby("pair").ms.max()
agg["length"] = fl.groupby("pair").length.first()
agg["highway"] = fl.groupby("pair").highway.first().map(first).astype(str)
geom = fl.groupby("pair").geometry.first()
R = gpd.GeoDataFrame(agg.join(geom), geometry="geometry", crs=fl.crs).reset_index()
print(f"undirected segments with any crossing: {len(R):,}", flush=True)

tot = {c: max(1, int(R[c].sum())) for c in C}
print("\ncrossings and roads reached by each filter:")
for i, t in enumerate(TH):
    print(f"  >= {t:>4} km/h : {tot[f'c{i}']:7,} crossings on {int((R[f'c{i}'] > 0).sum()):6,} roads")

# slow index: the road's share of the all-speeds draw against its share of the
# >= 20 km/h draw. Both draws are the same size, so this is just a count ratio.
lo, hi = R.c0.to_numpy(float), R.c8.to_numpy(float)
R["slow_index"] = np.where(hi > 0, (lo / tot["c0"]) / np.maximum(hi / tot["c8"], 1e-12), np.nan)
R.loc[(lo < 5) & (hi < 5), "slow_index"] = np.nan          # too thin to characterise

# Poisson uncertainty on the counts that drive the map
for name, c in [("all", "c0"), ("v20", "c8")]:
    k = R[c].to_numpy()
    R[f"rse_{name}"] = np.where(k > 0, 1 / np.sqrt(np.maximum(k, 1)), np.nan)
    R[f"lo95_{name}"] = np.where(k > 0, chi2.ppf(0.025, 2 * k) / 2, 0.0)
    R[f"hi95_{name}"] = chi2.ppf(0.975, 2 * (k + 1)) / 2

R.to_parquet(os.path.join(DER, "flowsense_sweep_roads.parquet"))

ok = R.slow_index.notna()
print(f"\nslow index on {int(ok.sum()):,} roads; median by speed limit:")
for sp, g in R[ok].groupby(R.ms.fillna(-1)):
    if len(g) >= 150 and sp > 0:
        print(f"  {int(sp):3d} km/h : n={len(g):6,}  median {g.slow_index.median():5.2f}")
thin = int((R.c0 < 5).sum())
print(f"\nuncertainty: {thin:,} of {len(R):,} roads carry fewer than 5 crossings at all speeds "
      f"({100*thin/len(R):.0f}%) - too thin to rank")
print(f"median relative standard error where counted: {np.nanmedian(R.rse_all):.0%}")
print(f"\nwrote flowsense_sweep.parquet and flowsense_sweep_roads.parquet -> {DER}")
