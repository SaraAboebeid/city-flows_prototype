"""Network position against observed flow.

Betweenness centrality asks a structural question: if everyone drove the
shortest route between every pair of places, which roads would they have to
use? Comparing that with what the phones actually saw separates two things:

  roads busy because the network funnels traffic there  (high centrality, high flow)
  roads busier or quieter than their position predicts  (the residual)

Method: the Trafikverket network shipped with FlowSense, as an undirected
graph weighted by length. Betweenness is estimated from K random source nodes
(Brandes' idea without the exact pair count): shortest-path trees from each
source, then every edge on the way back from each reachable node is credited.
The residual is the difference between a road's observed flow and the flow a
log-log fit of flow on centrality predicts for it.

Writes flowsense_centrality.parquet (pair, betweenness, predicted, residual).
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import FLOWSENSE, DER  # noqa: E402

import numpy as np
import pandas as pd
import geopandas as gpd
import pyogrio
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.stats import spearmanr

NET = os.path.join(FLOWSENSE, r"road_network\road_network\preprocessed\road_network_trafikverket_edges_gbg.geojson")
K = 400                     # sampled source nodes
RELIABLE = 5                # crossings before a road is used to fit
rng = np.random.default_rng(7)

net = pyogrio.read_dataframe(NET, columns=["u", "v", "key", "length"], read_geometry=False)
net["pair"] = [f"{min(a, b)}-{max(a, b)}-{k}" for a, b, k in
               zip(net.u.astype(np.int64), net.v.astype(np.int64), net.key.astype(int))]
E = net.groupby("pair").agg(u=("u", "first"), v=("v", "first"), length=("length", "first")).reset_index()
nodes = pd.Index(pd.unique(np.concatenate([E.u.values, E.v.values])))
E["ui"] = nodes.get_indexer(E.u.values); E["vi"] = nodes.get_indexer(E.v.values)
N, M = len(nodes), len(E)
# a matrix cell holds one value, so parallel edges between the same two nodes
# (key > 0) must collapse to one: keep the shortest, and credit it for all
E["a"] = np.minimum(E.ui, E.vi); E["b"] = np.maximum(E.ui, E.vi)
E["eidx"] = np.arange(M)
E = E[E.a != E.b]                                        # drop self loops
rep = E.sort_values("length").groupby(["a", "b"], sort=False).first().reset_index()
E["rep"] = E.set_index(["a", "b"]).index.map(
    pd.Series(np.arange(len(rep)), index=pd.MultiIndex.from_frame(rep[["a", "b"]])))
ai, bi = rep.a.to_numpy(), rep.b.to_numpy()
w = np.maximum(rep.length.to_numpy(float), 1.0)
P = len(rep)
print(f"graph: {N:,} nodes, {M:,} undirected edges, {P:,} distinct node pairs", flush=True)

# adjacency (both directions) and, in the same shape, the pair id + 1
G = csr_matrix((np.concatenate([w, w]), (np.concatenate([ai, bi]), np.concatenate([bi, ai]))),
               shape=(N, N))
ids = np.arange(P) + 1
EID = csr_matrix((np.concatenate([ids, ids]), (np.concatenate([ai, bi]), np.concatenate([bi, ai]))),
                 shape=(N, N))

CACHE = os.path.join(DER, "flowsense_betweenness.parquet")
bc = np.zeros(P, np.int64)
srcs = rng.choice(N, size=min(K, N), replace=False)
t0 = time.time()
if os.path.exists(CACHE):
    print(f"using cached betweenness ({CACHE}); delete it to recompute", flush=True)
    srcs = srcs[:0]
    E["betweenness"] = pd.read_parquet(CACHE).set_index("pair").betweenness.reindex(E.pair).values
for n, s in enumerate(srcs, 1):
    _, pred = dijkstra(G, directed=False, indices=int(s), return_predecessors=True)
    cur = np.flatnonzero(pred >= 0)
    while cur.size:
        p = pred[cur]
        eid = np.asarray(EID[p, cur]).ravel() - 1
        good = eid >= 0
        np.add.at(bc, eid[good], 1)
        cur = p[p >= 0]
    if n % 100 == 0:
        print(f"  {n}/{len(srcs)} sources ({time.time()-t0:.0f} s)", flush=True)

if len(srcs):
    E["betweenness"] = bc[E.rep.to_numpy()] / (len(srcs) * max(1, N - 1))   # share of sampled routes
    E[["pair", "betweenness"]].to_parquet(CACHE)
print(f"betweenness: median {np.median(E.betweenness):.2e}, max {E.betweenness.max():.2e}", flush=True)

# ---------- against the phones ----------
R = gpd.read_parquet(os.path.join(DER, "flowsense_sweep_roads.parquet"))
df = E.merge(R[["pair", "c0", "c8", "ms", "length"]].rename(columns={"length": "len_m"}),
             on="pair", how="left")
df[["c0", "c8"]] = df[["c0", "c8"]].fillna(0)
# fit across the whole observed range: restricting to busy roads truncates it
# and flattens the slope to nothing
fit = df[(df.c8 >= 1) & (df.betweenness > 0)]
x, y = np.log(fit.betweenness.to_numpy()), np.log(fit.c8.to_numpy())
slope, intercept = np.polyfit(x, y, 1)
print(f"\nfit on {len(fit):,} roads with any crossing at >= 20 km/h:")
print(f"  log(flow) = {slope:.2f} * log(betweenness) + {intercept:.2f}")
print(f"  Spearman flow vs betweenness: {spearmanr(fit.betweenness, fit.c8).statistic:.3f}")
busy = df[(df.c8 >= RELIABLE) & (df.betweenness > 0)]
print(f"  on the {len(busy):,} well-observed roads only: "
      f"{spearmanr(busy.betweenness, busy.c8).statistic:.3f} (range truncated)")
print(f"  all speeds, any crossing: {spearmanr(df[df.c0>0].betweenness, df[df.c0>0].c0).statistic:.3f}")

df["predicted"] = np.exp(slope * np.log(np.maximum(df.betweenness.to_numpy(), 1e-12)) + intercept)

# The mapped quantity is a rank difference, not the log-fit residual: the roads
# worth showing are the well-observed ones, and they are a busy subset of the
# fitted range, so a fitted residual would be biased upwards for all of them.
# Percentile of observed flow minus percentile of centrality, both taken over
# the same set, is unbiased and reads directly: +1 = far busier than its
# position in the network, -1 = far quieter.
base = df[(df.c8 >= 1) & (df.betweenness > 0)].copy()
pf = base.c8.rank(pct=True); pc = base.betweenness.rank(pct=True)
df["residual"] = np.nan
df.loc[base.index, "residual"] = (pf - pc).to_numpy()
df.loc[df.c8 < RELIABLE, "residual"] = np.nan        # too thin to characterise
ok = df.residual.notna()
print(f"\nrank difference (traffic percentile - centrality percentile) on {int(ok.sum()):,} roads: "
      f"deciles {np.round(np.percentile(df.residual[ok], [10, 25, 50, 75, 90]), 2)}")
print("  median residual by speed limit:")
for sp, g in df[ok].groupby(df.ms.fillna(-1)):
    if len(g) >= 150 and sp > 0:
        print(f"    {int(sp):3d} km/h : n={len(g):6,}  {g.residual.median():+5.2f}")

df[["pair", "betweenness", "predicted", "residual"]].to_parquet(
    os.path.join(DER, "flowsense_centrality.parquet"))
print(f"\nwrote flowsense_centrality.parquet -> {DER}")
