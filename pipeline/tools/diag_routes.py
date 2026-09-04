
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
import importlib
for m in ["networkx", "scipy"]:
    try:
        mod = importlib.import_module(m)
        print(f"{m:10s} {getattr(mod, '__version__', '?')}")
    except ImportError:
        print(f"{m:10s} MISSING")

import geopandas as gpd
g = gpd.read_file(os.path.join(DER, r"\transit_routes.gpkg".lstrip("\\")))
print("\nspine length by mode (km) — what we kept:")
print(g.groupby("mode").len_km.describe()[["count", "mean", "50%", "max"]].round(1).to_string())

import pyarrow.parquet as pq
t = pq.read_table(os.path.join(DER, r"\trips.parquet".lstrip("\\")),
                  columns=["mode", "routed", "lon", "lat"])
import pandas as pd
df = t.to_pandas()
tr = df[df["mode"].isin(["Train/Tram", "Bus", "Boat"])]
print(f"\ntransit trips: {len(tr):,}")
od = set()
for lo, la in zip(tr.lon.values, tr.lat.values):
    od.add((round(lo[0], 5), round(la[0], 5), round(lo[-1], 5), round(la[-1], 5)))
print(f"distinct O-D pairs among them: {len(od):,} "
      f"({100*len(od)/len(tr):.1f}% of trips) -> caching factor {len(tr)/len(od):.1f}x")
