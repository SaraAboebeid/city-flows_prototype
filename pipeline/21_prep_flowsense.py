"""Convert FlowSense Göteborg flows and ground truth into fast local files.

FlowSense (Teeuwen & Gil 2025, Zenodo 10.5281/zenodo.16794871) stores each
two-way road once per direction on the Trafikverket (NVDB) network. Here both
directions are summed into one undirected segment, so it compares with our
undirected street flows. Counts are trajectories from a sparse 2024 sample
(~100,000 trajectories), not vehicles per day.

Writes (EPSG:3006 geometry as WKB):
  flowsense_gbg.parquet      undirected NVDB segments: highway class, maxspeed,
                             length, obs_all (min avg speed 0), obs_20 (>= 20 km/h)
  groundtruth_gbg.parquet    2023 counts: Trafikverket highway links (ADT, all
                             vehicles) + Göteborg municipal count points (ÅDT)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import FLOWSENSE, DER  # noqa: E402

import numpy as np
import pandas as pd
import geopandas as gpd
import pyogrio

t0 = time.time()
FL = os.path.join(FLOWSENSE, r"traffic_flows\traffic_flows\flows_gbg_flows_2024_random1to2.geojson")
NET = os.path.join(FLOWSENSE, r"road_network\road_network\preprocessed\road_network_trafikverket_edges_gbg.geojson")
GT_HW = os.path.join(FLOWSENSE, r"ground_truth\ground_truth\preprocessed\ground_truth_flows_cars_gbg_highway_2023.geojson")
GT_LOC = os.path.join(FLOWSENSE, r"ground_truth\ground_truth\preprocessed\ground_truth_flows_cars_gbg_local_2023.geojson")

fl = pyogrio.read_dataframe(FL, columns=["maxspeed", "trajcount_minavgspeed0",
                                         "trajcount_minavgspeed20"])
print(f"read flows: {len(fl):,} directed edges ({time.time()-t0:.0f} s)", flush=True)
net = pyogrio.read_dataframe(NET, columns=["u", "v", "key", "highway", "length"],
                             read_geometry=False)
assert len(net) == len(fl), "flows and network are expected to align row by row"
fl = fl.join(net)

a, b = fl.u.astype(np.int64).values, fl.v.astype(np.int64).values
fl["pair"] = [f"{min(x, y)}-{max(x, y)}-{k}" for x, y, k in zip(a, b, fl.key.astype(int))]
agg = fl.groupby("pair").agg(
    obs_all=("trajcount_minavgspeed0", "sum"),
    obs_20=("trajcount_minavgspeed20", "sum"),
    highway=("highway", "first"), maxspeed=("maxspeed", "first"),
    length=("length", "first"), geometry=("geometry", "first"))
seg = gpd.GeoDataFrame(agg.reset_index(), geometry="geometry", crs="EPSG:3006")


def first(v):
    """merged edges carry lists of values (e.g. two speed limits): take the first"""
    if isinstance(v, (list, tuple, np.ndarray)):
        return v[0] if len(v) else None
    return v


seg["highway"] = seg.highway.map(first).astype(str)
seg["maxspeed"] = pd.to_numeric(seg.maxspeed.map(first), errors="coerce")
seg["obs_all"] = seg.obs_all.astype(int)
seg["obs_20"] = seg.obs_20.astype(int)
seg.to_parquet(os.path.join(DER, "flowsense_gbg.parquet"))
print(f"undirected segments: {len(seg):,} | with >=1 trajectory {int((seg.obs_all>0).sum()):,} "
      f"| >=5 {int((seg.obs_all>=5).sum()):,} | total trajectories {int(seg.obs_all.sum()):,}", flush=True)

# ---------- ground truth ----------
hw = pyogrio.read_dataframe(GT_HW, columns=["element_id", "direction", "adt_samtliga_fordon",
                                            "matmetod", "extent_length"])
hw = hw.to_crs(3006)
hw["geometry"] = hw.geometry.force_2d()
hw = hw.rename(columns={"adt_samtliga_fordon": "adt"})
hw["source"] = "Trafikverket highway link"
hw["name"] = hw.element_id
loc = pyogrio.read_dataframe(GT_LOC, columns=["mätplatsnamn", "riktning", "ådt"]).to_crs(3006)
loc = loc.rename(columns={"mätplatsnamn": "name", "riktning": "direction", "ådt": "adt"})
loc["source"] = "Göteborg municipal count"
gt = gpd.GeoDataFrame(pd.concat([hw[["name", "direction", "adt", "source", "geometry"]],
                                 loc[["name", "direction", "adt", "source", "geometry"]]],
                                ignore_index=True), crs="EPSG:3006")
gt["adt"] = pd.to_numeric(gt.adt, errors="coerce")
gt = gt[gt.adt > 0]
gt.to_parquet(os.path.join(DER, "groundtruth_gbg.parquet"))
print(f"ground truth: {len(gt):,} counts "
      f"({(gt.source.str.startswith('Traf')).sum()} highway links, "
      f"{(gt.source.str.startswith('Göt')).sum()} municipal points) | "
      f"direction values: {sorted(gt.direction.dropna().unique())[:8]}")
print(f"done in {time.time()-t0:.0f} s")
