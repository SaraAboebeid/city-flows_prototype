"""How sparse are the FlowSense counts, and how are edges keyed/directed?"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import FLOWSENSE  # noqa: E402
import numpy as np, pandas as pd, pyogrio

p = os.path.join(FLOWSENSE, r"traffic_flows\traffic_flows\flows_gbg_flows_2024_random1to2.geojson")
cols = ["RLID", "maxspeed", "trajcount_minavgspeed0", "trajcount_minavgspeed10",
        "trajcount_minavgspeed20", "relflow_minavgspeed0"]
f = pyogrio.read_dataframe(p, columns=cols)
net = pyogrio.read_dataframe(os.path.join(FLOWSENSE,
      r"road_network\road_network\preprocessed\road_network_trafikverket_edges_gbg.geojson"),
      columns=["u", "v", "key", "RLID", "highway", "length"], read_geometry=False)
print(f"{len(f):,} flow edges, {len(net):,} network edges")
f = f.join(net[["u", "v", "key", "highway", "length"]])

for c in ["trajcount_minavgspeed0", "trajcount_minavgspeed10", "trajcount_minavgspeed20"]:
    v = f[c].astype(float)
    print(f"\n{c}: nonzero {int((v>0).sum()):,} ({100*(v>0).mean():.1f}%) | sum {v.sum():,.0f} | "
          f"p50 {v[v>0].median():.0f} p90 {v[v>0].quantile(.9):.0f} p99 {v[v>0].quantile(.99):.0f} max {v.max():.0f}")

print("\nrelflow vs trajcount (is relflow = count / max?):",
      np.allclose(f.relflow_minavgspeed0.astype(float),
                  f.trajcount_minavgspeed0.astype(float) / f.trajcount_minavgspeed0.astype(float).max(), atol=1e-6))

# directed? do (u,v) and (v,u) both exist?
pairs = set(zip(f.u, f.v))
rev = sum((v, u) in pairs for u, v in pairs)
print(f"\nedges whose reverse also exists: {rev:,} of {len(pairs):,} -> "
      f"{'directed (two-way roads stored twice)' if rev > 0.3*len(pairs) else 'mostly one record per road'}")
print(f"unique RLID strings: {f.RLID.nunique():,}")

print("\nby road class (nonzero share, median count where >0):")
g = f.assign(c=f.trajcount_minavgspeed0.astype(float))
t = g.groupby("highway").c.agg(edges="size", nonzero=lambda s: (s > 0).mean(), med=lambda s: s[s > 0].median())
print(t.sort_values("edges", ascending=False).head(12).round(2).to_string())
