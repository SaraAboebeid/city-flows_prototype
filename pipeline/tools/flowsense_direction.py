"""Do the two directions of a FlowSense road carry different counts?
If yes, the data holds real direction-of-travel information."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import FLOWSENSE  # noqa: E402
import numpy as np, pandas as pd, pyogrio

fl = pyogrio.read_dataframe(os.path.join(FLOWSENSE,
      r"traffic_flows\traffic_flows\flows_gbg_flows_2024_random1to2.geojson"),
      columns=["trajcount_minavgspeed0", "trajcount_minavgspeed20"], read_geometry=False)
net = pyogrio.read_dataframe(os.path.join(FLOWSENSE,
      r"road_network\road_network\preprocessed\road_network_trafikverket_edges_gbg.geojson"),
      columns=["u", "v", "key"], read_geometry=False)
d = fl.join(net)
d["u"], d["v"], d["key"] = d.u.astype(int), d.v.astype(int), d.key.astype(int)
fw = d.set_index(["u", "v", "key"])
m = d.merge(d, left_on=["u", "v", "key"], right_on=["v", "u", "key"], suffixes=("", "_rev"))
m = m[m.u < m.v]                                   # each road once
for c in ["trajcount_minavgspeed0", "trajcount_minavgspeed20"]:
    a, b = m[c].astype(float), m[c + "_rev"].astype(float)
    seen = (a + b) > 0
    print(f"{c}: roads seen {int(seen.sum()):,} | identical both ways {100*(a[seen]==b[seen]).mean():.1f}% "
          f"| one direction only {100*((a[seen]==0)|(b[seen]==0)).mean():.1f}%")
    busy = (a + b) >= 10
    share = (np.maximum(a, b) / (a + b))[busy]
    print(f"   roads with >=10: {int(busy.sum()):,}, median share of the busier direction {share.median():.2f}")
