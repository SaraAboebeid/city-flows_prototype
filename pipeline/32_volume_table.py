"""VOLUME values, traced back to the FlowSense source file.

    python 32_volume_table.py              whole Göteborg file (default)
    python 32_volume_table.py torslanda    the Torslanda box only

For every road the dashboard draws in the area, list the rows of
flows_gbg_flows_2024_random1to2.geojson it comes from (one row per direction of
travel), their raw trajcount_minavgspeed<N> values, the sum of both directions,
and the value the dashboard actually carries for that road, so the two can be
compared line by line.

How a dashboard road maps to the source:
  - the flows file and the Trafikverket network file align row by row (checked:
    127,290 identical geometries), so source row i has the network's u, v, key
  - stage 28 sums both directions of the same (u, v, key) segment into one road
  - stage 30 keeps stage 28's road order, so dashboard road i = stage 28 row i

Identifiers are the source's own: RLID is Trafikverket's NVDB reference link
("Referenslänkens OID", see road_network/raw/Kolumnnamn.txt) and ISA_index the
FlowSense edge index. The network file's "osmid" column is not an OSM id - it
repeats ISA_index - so it is reported under that name.

Street names, road numbers, road managers and speed limits are not in the
source: they are looked up by RLID in NVDB through Trafikverket's API (nvdb.py,
needs TRAFIKVERKET_API_KEY in ../.env).

Writes ../exports/<area>_volume_roads.csv     one row per road on the map
       ../exports/<area>_volume_directed.csv  one row per source record
"""
import os, sys, json, gzip, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import FLOWSENSE, DER, PHONEWEB  # noqa: E402

import numpy as np
import pandas as pd
import pyogrio
import pyarrow.parquet as pq
import shapely
import nvdb  # noqa: E402

# the area to export: the whole FlowSense Göteborg file (default) or a lon/lat box
AREAS = {"goteborg": None,
         "torslanda": (11.70, 57.68, 11.86, 57.75)}   # Torslanda and the Torslandavägen corridor
AREA = sys.argv[1] if len(sys.argv) > 1 else "goteborg"
BOX = AREAS[AREA]
SRC = os.path.join(FLOWSENSE, r"traffic_flows\traffic_flows\flows_gbg_flows_2024_random1to2.geojson")
NET = os.path.join(FLOWSENSE, r"road_network\road_network\preprocessed\road_network_trafikverket_edges_gbg.geojson")
TH = ["0", "2.5", "5", "7.5", "10", "12.5", "15", "17.5", "20"]
COLS = [f"trajcount_minavgspeed{t}" for t in TH]
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exports")
os.makedirs(OUT, exist_ok=True)
first = lambda v: (v[0] if len(v) else None) if isinstance(v, (list, np.ndarray)) else v

# ---------- source records ----------
fl = pyogrio.read_dataframe(SRC, columns=["ISA_index", "RLID", "maxspeed"] + COLS)
net = pyogrio.read_dataframe(NET, columns=["u", "v", "key", "highway", "length"])
assert len(fl) == len(net) and shapely.equals_exact(fl.geometry.values, net.geometry.values, 1e-6).all()
fl = fl.join(net.drop(columns="geometry"))
flat = lambda v: " ".join(map(str, v)) if isinstance(v, (list, np.ndarray)) else str(v)
fl["RLID"], fl["ISA_index"] = fl.RLID.map(flat), fl.ISA_index.map(flat)
fl["source_row"] = np.arange(len(fl))
a, b = fl.u.astype(np.int64).values, fl.v.astype(np.int64).values
fl["pair"] = [f"{min(x, y)}-{max(x, y)}-{k}" for x, y, k in zip(a, b, fl.key.astype(int))]
g = fl.to_crs(4326).geometry.values
mid = shapely.line_interpolate_point(g, 0.5, normalized=True)
fl["lon"], fl["lat"] = np.round(shapely.get_x(mid), 5), np.round(shapely.get_y(mid), 5)
fl["from_lon"], fl["from_lat"] = np.round(shapely.get_x(shapely.get_point(g, 0)), 5), np.round(shapely.get_y(shapely.get_point(g, 0)), 5)
fl["to_lon"], fl["to_lat"] = np.round(shapely.get_x(shapely.get_point(g, -1)), 5), np.round(shapely.get_y(shapely.get_point(g, -1)), 5)
for c in COLS:
    fl[c] = fl[c].fillna(0).astype(int)

# ---------- dashboard roads, in stage 28 order ----------
R = pq.read_table(os.path.join(DER, "flowsense_sweep_roads.parquet"), columns=["pair"]).to_pandas()
D = json.load(open(os.path.join(PHONEWEB, "data", "sweep.json"), encoding="utf-8"))
assert D["roads"]["n"] == len(R), "sweep.json is not in stage 28 order - rerun stages 28 and 30"
dash = np.column_stack([np.frombuffer(gzip.decompress(base64.b64decode(s)), np.uint16)
                        for s in D["roads"]["counts"]])
R[[f"dashboard_{t}" for t in TH]] = dash.astype(int)

# a road is in a box when the midpoint of its first source record is in it
pm = fl.groupby("pair")[["lon", "lat"]].first()
R = R.join(pm, on="pair")
if BOX:
    R = R[(R.lon >= BOX[0]) & (R.lon <= BOX[2]) & (R.lat >= BOX[1]) & (R.lat <= BOX[3])].copy()
R["dashboard_road"] = R.index
src = fl[fl.pair.isin(R.pair)].copy()

# ---------- NVDB data for each RLID (Trafikverket API) ----------
NV = ["nvdb_street_name", "nvdb_road_number", "nvdb_road_manager", "nvdb_speed_limit"]
ids = sorted({r for v in src.RLID for r in v.split()})
info = nvdb.lookup(ids)


def nvdb_cols(rlid):
    parts = [nvdb.describe(info.get(r)) for r in rlid.split()]
    return pd.Series({c: " / ".join(dict.fromkeys(p[c] for p in parts if p[c])) for c in NV})


src[NV] = src.RLID.apply(nvdb_cols)

# ---------- roads: source sum next to the dashboard value ----------
S = src.groupby("pair").agg(RLID=("RLID", lambda s: " | ".join(dict.fromkeys(s))),
                            ISA_index=("ISA_index", lambda s: " | ".join(dict.fromkeys(s))),
                            source_rows=("source_row", lambda s: " + ".join(map(str, sorted(s)))),
                            n_directions=("source_row", "size"),
                            **{c: (c, lambda s: " / ".join(dict.fromkeys(v for v in s if v))) for c in NV},
                            highway=("highway", lambda s: first(s.iloc[0])),
                            maxspeed=("maxspeed", lambda s: first(s.iloc[0])),
                            length_m=("length", "first"),
                            **{f"source_sum_{t}": (c, "sum") for t, c in zip(TH, COLS)})
R = R.join(S, on="pair")
R["matches"] = np.all([R[f"source_sum_{t}"] == R[f"dashboard_{t}"] for t in TH], axis=0)
R["length_m"] = R.length_m.round(1)
roads = R[["RLID"] + NV + ["ISA_index", "source_rows", "n_directions", "dashboard_road", "highway",
           "maxspeed", "length_m", "lon", "lat"]
          + [f"source_sum_{t}" for t in TH] + [f"dashboard_{t}" for t in TH] + ["matches"]]
roads = roads.sort_values(["source_sum_0", "source_sum_20"], ascending=False)
roads.to_csv(os.path.join(OUT, f"{AREA}_volume_roads.csv"), index=False, encoding="utf-8-sig")

directed = src[["source_row", "RLID"] + NV + ["ISA_index", "u", "v", "key", "highway",
                "maxspeed", "length", "from_lon", "from_lat", "to_lon", "to_lat"] + COLS]
directed = directed.assign(highway=directed.highway.map(first), maxspeed=directed.maxspeed.map(first),
                           length=directed.length.round(1)).sort_values(["RLID", "source_row"])
directed.to_csv(os.path.join(OUT, f"{AREA}_volume_directed.csv"), index=False, encoding="utf-8-sig")

print(f"{AREA} {BOX or '(whole file)'}: {len(roads):,} roads on the map from {len(directed):,} source records")
print(f"  all speeds: source {int(roads.source_sum_0.sum()):,} = dashboard {int(roads.dashboard_0.sum()):,}; "
      f">= 20 km/h: source {int(roads.source_sum_20.sum()):,} = dashboard {int(roads.dashboard_20.sum()):,}")
print(f"  roads where every filter matches: {int(roads.matches.sum()):,} of {len(roads):,}")
print(f"  roads with an NVDB street name: {int((roads.nvdb_street_name != '').sum()):,}, "
      f"road number: {int((roads.nvdb_road_number != '').sum()):,}, "
      f"speed limit: {int((roads.nvdb_speed_limit != '').sum()):,} of {len(roads):,}")
print(f"wrote {AREA}_volume_roads.csv and {AREA}_volume_directed.csv -> {OUT}")

# ---------- the dashboard's lookup: RLID and NVDB data per map road ----------
# arrays in dashboard road order; the text fields index a shared string table
if BOX is None:
    n = D["roads"]["n"]
    sid = {"": 0}
    col = lambda s: [sid.setdefault(v, len(sid)) for v in s]
    full = roads.set_index("dashboard_road").reindex(range(n)).fillna("")
    lut = {"n": n, "source": "NVDB via Trafikverket open API, looked up by RLID (Element_Id)",
           **{k: col(full[c]) for k, c in [("rlid", "RLID"), ("name", "nvdb_street_name"),
                                           ("road", "nvdb_road_number"), ("manager", "nvdb_road_manager"),
                                           ("speed", "nvdb_speed_limit")]}}
    lut["strings"] = list(sid)
    path = os.path.join(PHONEWEB, "data", "nvdb.json")
    json.dump(lut, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {path} ({os.path.getsize(path) / 1e6:.1f} MB, {len(sid):,} strings)")
