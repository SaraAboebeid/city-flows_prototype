"""Fetch Gothenburg public-transport route geometries from OSM Overpass
and stitch each relation's member ways into a single LineString.
Saves EPSG:3006 geometry to _derived/transit_routes.gpkg
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
import requests, time, os, collections
import numpy as np
import geopandas as gpd
from shapely.geometry import LineString
from shapely.ops import linemerge
from pyproj import Transformer

OUT = DER
os.makedirs(OUT, exist_ok=True)
BBOX = "57.5033,11.5909,57.9163,12.2684"
URL = "https://overpass-api.de/api/interpreter"
HDR = {"User-Agent": "gbg-synthpop-research/1.0"}

tf = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)

rows = []
for mode in ["tram", "bus", "ferry", "train", "light_rail", "subway"]:
    q = f"""
    [out:json][timeout:600];
    relation({BBOX})["type"="route"]["route"="{mode}"];
    out geom;
    """
    for attempt in range(3):
        try:
            r = requests.post(URL, data={"data": q}, headers=HDR, timeout=900)
            r.raise_for_status()
            els = r.json()["elements"]
            break
        except Exception as e:
            print(f"  {mode}: attempt {attempt+1} failed: {e}", flush=True)
            time.sleep(20)
    else:
        print(f"  {mode}: GIVING UP", flush=True)
        continue

    kept = 0
    for e in els:
        segs = []
        for m in e.get("members", []):
            g = m.get("geometry")
            if m.get("type") == "way" and g and len(g) > 1:
                segs.append(LineString([(p["lon"], p["lat"]) for p in g]))
        if not segs:
            continue
        merged = linemerge(segs)
        parts = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
        parts = [p for p in parts if p.length > 0]
        if not parts:
            continue
        # keep the longest continuous run as the route spine
        spine = max(parts, key=lambda p: p.length)
        xs, ys = tf.transform(*np.array(spine.coords).T)
        t = e.get("tags", {})
        rows.append({
            "osm_id": e["id"],
            "mode": mode,
            "ref": t.get("ref"),
            "name": t.get("name"),
            "operator": t.get("operator"),
            "n_parts": len(parts),
            "geometry": LineString(np.column_stack([xs, ys])),
        })
        kept += 1
    print(f"{mode:12s} relations={len(els):>4}  usable={kept:>4}", flush=True)
    time.sleep(5)

gdf = gpd.GeoDataFrame(rows, crs="EPSG:3006")
gdf["len_km"] = gdf.length / 1000
path = os.path.join(OUT, "transit_routes.gpkg")
gdf.to_file(path, driver="GPKG", layer="routes")

print(f"\nsaved {len(gdf)} routes -> {path}")
print(gdf.groupby("mode").agg(n=("osm_id", "size"),
                              km=("len_km", "sum")).round(1).to_string())
frag = (gdf.n_parts > 1).sum()
print(f"\nrelations that did not merge into one continuous line: {frag} "
      f"({100*frag/len(gdf):.0f}%) - spine = longest run")
