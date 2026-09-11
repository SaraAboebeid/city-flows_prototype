"""What is inside the FlowSense files? Schema, CRS, counts, value ranges."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import FLOWSENSE  # noqa: E402
import pyogrio

FILES = [
    r"traffic_flows\traffic_flows\flows_gbg_flows_2024_random1to2.geojson",
    r"road_network\road_network\preprocessed\road_network_trafikverket_edges_gbg.geojson",
    r"ground_truth\ground_truth\preprocessed\ground_truth_flows_cars_gbg_highway_2023.geojson",
    r"ground_truth\ground_truth\preprocessed\ground_truth_flows_cars_gbg_local_2023.geojson",
]
for rel in FILES:
    p = os.path.join(FLOWSENSE, rel)
    info = pyogrio.read_info(p)
    print(f"\n=== {os.path.basename(p)} ===")
    print(f"  features {info['features']:,} | geometry {info['geometry_type']} | crs {info['crs']}")
    print(f"  fields: {list(info['fields'])}")
    df = pyogrio.read_dataframe(p, max_features=2000)
    num = df.select_dtypes("number")
    if len(num.columns):
        print(num.describe().T[["min", "50%", "max"]].round(2).head(20).to_string())
    print("  first row:", {k: (str(v)[:60]) for k, v in df.drop(columns="geometry").iloc[0].items()})

print("\n=== links to Gothenburg 2023 data.txt ===")
print(open(os.path.join(FLOWSENSE, r"ground_truth\ground_truth\raw\links to Gothenburg 2023 data.txt"),
           encoding="utf-8", errors="replace").read()[:1500])
