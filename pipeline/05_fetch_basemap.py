"""Richer Gothenburg basemap: filled water polygons, coastline, and a
two-tier road network. Saves _derived/basemap2.json
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
import requests, json, os, time
import numpy as np
from shapely.geometry import LineString, Polygon
from pyproj import Transformer

BBOX = "57.5033,11.5909,57.9163,12.2684"
URL = "https://overpass-api.de/api/interpreter"
HDR = {"User-Agent": "gbg-synthpop-research/1.0"}

to3006 = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)
to4326 = Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)


def fetch(q, label):
    for a in range(4):
        try:
            r = requests.post(URL, data={"data": q}, headers=HDR, timeout=900)
            r.raise_for_status()
            return r.json()["elements"]
        except Exception as e:
            print(f"  {label} attempt {a+1}: {e}", flush=True)
            time.sleep(25)
    return []


def geom_of(e):
    g = e.get("geometry")
    if g and len(g) > 1:
        return np.array([[p["lon"], p["lat"]] for p in g], dtype=float)
    return None


def simp_line(arr, tol):
    x, y = to3006.transform(arr[:, 0], arr[:, 1])
    ln = LineString(np.column_stack([x, y])).simplify(tol)
    if ln.is_empty or len(ln.coords) < 2:
        return None
    xs, ys = np.array(ln.coords).T
    lo, la = to4326.transform(xs, ys)
    return [[round(float(a), 5), round(float(b), 5)] for a, b in zip(lo, la)]


def simp_poly(arr, tol, min_area):
    if len(arr) < 4:
        return None
    x, y = to3006.transform(arr[:, 0], arr[:, 1])
    try:
        pg = Polygon(np.column_stack([x, y]))
        if not pg.is_valid:
            pg = pg.buffer(0)
        if pg.is_empty or pg.area < min_area:
            return None
        pg = pg.simplify(tol)
        if pg.is_empty or pg.geom_type != "Polygon":
            return None
        xs, ys = np.array(pg.exterior.coords).T
    except Exception:
        return None
    lo, la = to4326.transform(xs, ys)
    return [[round(float(a), 5), round(float(b), 5)] for a, b in zip(lo, la)]


out = {}

# --- water polygons (ways + multipolygon relation outers) ---
q = (f'[out:json][timeout:900];'
     f'(way({BBOX})["natural"="water"];'
     f' way({BBOX})["waterway"="riverbank"];'
     f' relation({BBOX})["natural"="water"];);out geom;')
els = fetch(q, "water")
polys = []
for e in els:
    if e["type"] == "way":
        a = geom_of(e)
        if a is not None:
            p = simp_poly(a, 25, 12000)
            if p:
                polys.append(p)
    else:
        for m in e.get("members", []):
            if m.get("role") == "outer" and m.get("type") == "way":
                g = m.get("geometry")
                if g and len(g) > 3:
                    a = np.array([[p["lon"], p["lat"]] for p in g], dtype=float)
                    p = simp_poly(a, 25, 12000)
                    if p:
                        polys.append(p)
out["water"] = polys
print(f"water polygons {len(polys):,}", flush=True)
time.sleep(8)

# --- coastline ---
q = f'[out:json][timeout:900];way({BBOX})["natural"="coastline"];out geom;'
lines = []
for e in fetch(q, "coast"):
    a = geom_of(e)
    if a is not None:
        s = simp_line(a, 25)
        if s:
            lines.append(s)
out["coast"] = lines
print(f"coast lines {len(lines):,}", flush=True)
time.sleep(8)

# --- major roads ---
q = (f'[out:json][timeout:900];'
     f'way({BBOX})["highway"~"^(motorway|trunk|primary)$"];out geom;')
maj = []
for e in fetch(q, "major"):
    a = geom_of(e)
    if a is not None:
        s = simp_line(a, 20)
        if s:
            maj.append(s)
out["major"] = maj
print(f"major roads {len(maj):,}", flush=True)
time.sleep(8)

# --- minor roads (texture) ---
q = (f'[out:json][timeout:900];'
     f'way({BBOX})["highway"~"^(secondary|tertiary|residential)$"];out geom;')
mnr = []
for e in fetch(q, "minor"):
    a = geom_of(e)
    if a is not None:
        s = simp_line(a, 35)
        if s:
            mnr.append(s)
out["minor"] = mnr
print(f"minor roads {len(mnr):,}", flush=True)

path = os.path.join(DER, "basemap2.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, separators=(",", ":"))
pts = sum(len(l) for v in out.values() for l in v)
print(f"\nsaved {path}  {os.path.getsize(path)/1e6:.2f} MB, {pts:,} vertices")
