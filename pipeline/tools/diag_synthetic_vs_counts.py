"""Why do synthetic car flows correlate weakly with real counts?
Checks: the busiest counted roads, the Torslanda distortion, speed classes."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DER  # noqa: E402
import numpy as np, pandas as pd
from scipy.stats import spearmanr

P = json.load(open(os.path.join(DER, "phone_payload.json"), encoding="utf-8"))
g = pd.DataFrame(P["ground"]).dropna(subset=["syn"])
print(f"{len(g)} counts with a synthetic value\n")
print("busiest 12 counted roads (real ADT, synthetic car trips/day, phone trajectories):")
print(g.nlargest(12, "adt")[["src", "name", "adt", "syn", "phone", "lon", "lat"]].to_string(index=False))

print("\nquietest counted roads where synthetic is highest (possible over-prediction):")
print(g.nlargest(8, "syn")[["src", "name", "adt", "syn", "phone", "lon", "lat"]].to_string(index=False))

# Torslanda / Volvo box in WGS84 (approx.)
tors = (g.lon < 11.90) & (g.lat > 57.70) & (g.lat < 57.74)
print(f"\ncounts inside the Torslanda/Volvo area: {int(tors.sum())}")
for lab, sub in [("all", g), ("excluding Torslanda", g[~tors])]:
    print(f"  {lab:22s} synthetic vs counts: rho = {spearmanr(sub.syn, sub.adt).statistic:.3f} (n={len(sub)})")

print("\nratio synthetic/real by count size (median):")
g["ratio"] = g.syn / g.adt
g["band"] = pd.cut(g.adt, [0, 2000, 5000, 15000, 30000, 1e6],
                   labels=["<2k", "2-5k", "5-15k", "15-30k", ">30k"])
print(g.groupby("band", observed=True).ratio.median().round(2).to_string())
print(f"\nshare of counts where synthetic is zero: {100*(g.syn == 0).mean():.0f}%")
