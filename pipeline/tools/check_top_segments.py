"""Sanity check: what are the busiest street segments, and are they real
bottlenecks (bridges, tunnels, motorway links) or artefacts?"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DER  # noqa: E402
import pandas as pd
import pyarrow.parquet as pq

day = pq.read_table(os.path.join(DER, "street_flows_day.parquet")).to_pandas()
st = pq.read_table(os.path.join(DER, "streets.parquet"),
                   columns=["edge_id", "highway", "name", "length_m", "lon", "lat"]).to_pandas()
m = day.merge(st, on="edge_id")
cols = ["trips", "mode:Car", "mode:Walking", "mode:Bicycle/E-bike", "highway", "name", "length_m"]
top = m.nlargest(15, "trips")
top["at"] = [f"{lo[len(lo)//2]:.4f},{la[len(la)//2]:.4f}" for lo, la in zip(top.lon, top.lat)]
print(top[cols + ["at"]].round(1).to_string(index=False))

print("\nvolume distribution over segments carrying trips:")
print(m.trips.describe(percentiles=[.5, .9, .99, .999]).round(0).to_string())

print("\nbusiest named streets (peak segment):")
g = m[m.name.notna()].groupby("name").trips.max().nlargest(12)
print(g.to_string())
