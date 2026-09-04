"""Extract all trips from the 94 Gothenburg synthetic-population .db files
into a single Parquet file, reprojected SWEREF99 TM (EPSG:3006) -> WGS84.

Output columns:
  person, neighborhood, mode, purpose_from, purpose_to,
  t_start, t_end        seconds from midnight (float)
  lon, lat              list<double>, the route polyline vertices
  n_pts                 vertex count (2 == no real routed geometry)
  routed                bool, True if n_pts > 2
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
import sqlite3, glob, os, re, sys
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Transformer

SRC = DATA
OUT = os.path.join(DER, r"\trips.parquet".lstrip("\\"))
os.makedirs(os.path.dirname(OUT), exist_ok=True)

TIME = re.compile(
    r"Start Time:\s*(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?),\s*"
    r"End Time:\s*(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)")
NUMS = re.compile(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?")

tf = Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)

SCHEMA = pa.schema([
    ("person", pa.string()),
    ("neighborhood", pa.string()),
    ("mode", pa.string()),
    ("purpose_from", pa.string()),
    ("purpose_to", pa.string()),
    ("t_start", pa.float64()),
    ("t_end", pa.float64()),
    ("lon", pa.list_(pa.float64())),
    ("lat", pa.list_(pa.float64())),
    ("n_pts", pa.int32()),
    ("routed", pa.bool_()),
])


def secs(h, m, s):
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_line(wkt):
    """LINESTRING (x y, x y, ...) -> (xs, ys). Returns None if unusable."""
    if not wkt or wkt == "None":
        return None
    v = NUMS.findall(wkt)
    if len(v) < 4:
        return None
    a = np.asarray(v, dtype=float)
    if a.size % 2:
        a = a[:-1]
    return a[0::2], a[1::2]


files = sorted(glob.glob(os.path.join(SRC, "*.db")))
writer = pq.ParquetWriter(OUT, SCHEMA, compression="zstd")

tot = skipped = 0
for fi, path in enumerate(files, 1):
    hood = os.path.basename(path)[22:-3]
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT uuid_person, mode, origin_purpose, destination_purpose, "
        "transit_activity, route, origin, destination FROM od_matrix").fetchall()
    con.close()

    cols = {k: [] for k in
            ("person", "mode", "purpose_from", "purpose_to",
             "t_start", "t_end", "lon", "lat", "n_pts", "routed")}

    for uid, mode, pf, pt, ta, route, o, d in rows:
        m = TIME.search(ta or "")
        if not m:
            skipped += 1
            continue
        t0 = secs(*m.group(1, 2, 3))
        t1 = secs(*m.group(4, 5, 6))
        if t1 < t0:                       # crosses midnight
            t1 += 86400

        pts = parse_line(route)
        if pts is None:                   # fall back to a 2-point O->D line
            no = NUMS.findall(o or ""); nd = NUMS.findall(d or "")
            if len(no) < 2 or len(nd) < 2:
                skipped += 1
                continue
            xs = np.array([float(no[0]), float(nd[0])])
            ys = np.array([float(no[1]), float(nd[1])])
        else:
            xs, ys = pts

        lon, lat = tf.transform(xs, ys)
        cols["person"].append(uid)
        cols["mode"].append(mode)
        cols["purpose_from"].append(pf)
        cols["purpose_to"].append(pt)
        cols["t_start"].append(t0)
        cols["t_end"].append(t1)
        cols["lon"].append(lon.tolist())
        cols["lat"].append(lat.tolist())
        cols["n_pts"].append(len(lon))
        cols["routed"].append(len(lon) > 2)

    n = len(cols["person"])
    tot += n
    writer.write_table(pa.table({
        "person": pa.array(cols["person"], pa.string()),
        "neighborhood": pa.array([hood] * n, pa.string()),
        "mode": pa.array(cols["mode"], pa.string()),
        "purpose_from": pa.array(cols["purpose_from"], pa.string()),
        "purpose_to": pa.array(cols["purpose_to"], pa.string()),
        "t_start": pa.array(cols["t_start"], pa.float64()),
        "t_end": pa.array(cols["t_end"], pa.float64()),
        "lon": pa.array(cols["lon"], pa.list_(pa.float64())),
        "lat": pa.array(cols["lat"], pa.list_(pa.float64())),
        "n_pts": pa.array(cols["n_pts"], pa.int32()),
        "routed": pa.array(cols["routed"], pa.bool_()),
    }, schema=SCHEMA))

    print(f"[{fi:>2}/94] {hood:<28} {n:>7,} trips", flush=True)

writer.close()
size = os.path.getsize(OUT) / 1e6
print(f"\nwrote {tot:,} trips  (skipped {skipped:,})  -> {OUT}  ({size:.0f} MB)")
