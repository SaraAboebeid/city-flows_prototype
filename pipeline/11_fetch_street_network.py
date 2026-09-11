"""Fetch the full OSM street network (roads, cycleways, footways) and split it
into segments at intersections - the unit that flows are counted on.

The dataset's own routes sit on OSM nodes (72% of vertices within 0.1 m of
one in a central-Göteborg probe), so trips can be projected onto these
segments almost exactly.

Raw Overpass responses are cached per tile in <DER>/osm_streets/.
Writes streets.parquet (one row per segment, WGS84 + length).
"""
import os, sys, json, time, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DER  # noqa: E402

import numpy as np
import requests
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Geod

S, W, N, E = 57.5033, 11.5909, 57.9163, 12.2684
TILES = 4
CACHE = os.path.join(DER, "osm_streets")
OUT = os.path.join(DER, "streets.parquet")
# public Overpass instances; rotate on timeouts / rate limits
MIRRORS = ["https://overpass-api.de/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter",
           "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
HDR = {"User-Agent": "gbg-synthpop-research/1.0"}

# not part of a routable network
SKIP = {"proposed", "construction", "platform", "bus_stop", "elevator",
        "raceway", "abandoned", "disused", "razed", "rest_area", "services",
        "emergency_bay", "corridor", "via_ferrata"}

os.makedirs(CACHE, exist_ok=True)
geod = Geod(ellps="WGS84")


def fetch_bbox(s, w, n, e, path, label, depth=0):
    """Fetch one bbox; if every mirror times out, split it into quarters."""
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    # 'tags' verbosity + geom: coordinates but no node ids. Shared OSM nodes
    # have identical coordinates, so splitting keys on coordinates instead.
    q = (f'[out:json][timeout:600];'
         f'way({s:.5f},{w:.5f},{n:.5f},{e:.5f})["highway"];out geom tags;')
    tries = 4 if depth < 2 else 10
    for a in range(tries):
        url = MIRRORS[a % len(MIRRORS)]
        try:
            r = requests.post(url, data={"data": q}, headers=HDR, timeout=900)
            r.raise_for_status()
            els = r.json()["elements"]
            json.dump(els, open(path, "w", encoding="utf-8"))
            return els
        except Exception as ex:
            print(f"    {label} attempt {a+1} ({url.split('/')[2]}): "
                  f"{str(ex)[:80]}", flush=True)
            time.sleep(8 + 4 * a)
    if depth >= 2:
        raise RuntimeError(f"{label} failed")
    print(f"    {label}: splitting into quarters", flush=True)
    ms, mw = (s + n) / 2, (w + e) / 2
    els = []
    for k, (a_, b_, c_, d_) in enumerate([(s, w, ms, mw), (s, mw, ms, e),
                                          (ms, w, n, mw), (ms, mw, n, e)]):
        els += fetch_bbox(a_, b_, c_, d_, path.replace(".json", f"_{k}.json"),
                          f"{label}.{k}", depth + 1)
    json.dump(els, open(path, "w", encoding="utf-8"))
    return els


def fetch_tile(i, j):
    s = S + (N - S) * i / TILES; n = S + (N - S) * (i + 1) / TILES
    w = W + (E - W) * j / TILES; e = W + (E - W) * (j + 1) / TILES
    return fetch_bbox(s, w, n, e, os.path.join(CACHE, f"tile_{i}_{j}.json"),
                      f"tile {i},{j}")


ways = {}
for i in range(TILES):
    for j in range(TILES):
        els = fetch_tile(i, j)
        for e in els:
            if e.get("type") != "way":
                continue
            hw = e.get("tags", {}).get("highway")
            if hw in SKIP or not e.get("geometry"):
                continue
            ways[e["id"]] = e
        print(f"  tile {i},{j}: {len(els):>6,} ways  (unique so far {len(ways):,})",
              flush=True)
        time.sleep(4)

def node_keys(g):
    """a node's coordinates, to 1e-7 deg, identify it across ways"""
    return [(round(p["lon"] * 1e7), round(p["lat"] * 1e7)) for p in g]


# a node is a split point if it ends a way or is shared by several ways
use = collections.Counter()
for w in ways.values():
    nd = node_keys(w["geometry"])
    use.update(nd)
    use[nd[0]] += 1
    use[nd[-1]] += 1

rows = {k: [] for k in ("edge_id", "way_id", "highway", "name",
                        "length_m", "lon", "lat")}
eid = 0
for w in ways.values():
    g = w["geometry"]
    nd = node_keys(g)
    tags = w.get("tags", {})
    start = 0
    for k in range(1, len(nd)):
        if use[nd[k]] > 1 or k == len(nd) - 1:
            seg = g[start:k + 1]
            if len(seg) >= 2:
                lo = [p["lon"] for p in seg]; la = [p["lat"] for p in seg]
                length = geod.line_length(lo, la)
                if length > 0:
                    rows["edge_id"].append(eid)
                    rows["way_id"].append(w["id"])
                    rows["highway"].append(tags.get("highway"))
                    rows["name"].append(tags.get("name"))
                    rows["length_m"].append(float(length))
                    rows["lon"].append(lo)
                    rows["lat"].append(la)
                    eid += 1
            start = k

pq.write_table(pa.table(rows), OUT, compression="zstd")
L = np.array(rows["length_m"])
hw = collections.Counter(rows["highway"])
print(f"\n{len(ways):,} ways -> {eid:,} segments, {L.sum()/1000:,.0f} km of network")
print(f"segment length: median {np.median(L):.0f} m, 95th pct "
      f"{np.percentile(L, 95):.0f} m")
print("top classes:", ", ".join(f"{k}={v:,}" for k, v in hw.most_common(10)))
print(f"wrote {OUT} ({os.path.getsize(OUT)/1e6:.0f} MB)")
