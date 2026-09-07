"""Aggregate every trip into a 200 m grid, by hour, to show where and when the
network actually carries load.

A cell is counted once per trip per hour (trips present, not vertices), so
dense route geometry does not inflate the value.

Writes load_grid.json  ->  cells (lon/lat) + a 21 x ncell count matrix
"""
import os, sys, json, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DER  # noqa: E402

import numpy as np
import pyarrow.parquet as pq
from pyproj import Transformer

SRC = os.path.join(DER, "trips_final.parquet")
if not os.path.exists(SRC):
    SRC = os.path.join(DER, "trips_routed2.parquet")
OUT = os.path.join(DER, "load_grid.json")

CELL = 100.0                      # metres; 100 m ~ street-block resolution
X0, Y0 = 299000.0, 6383900.0
NX = int(np.ceil(36000 / CELL)) + 1
NY = int(np.ceil(33400 / CELL)) + 1
NCELL = NX * NY
H0, H1 = 3, 23                    # hour bins, inclusive
NBIN = H1 - H0 + 1
BIG = NBIN * NCELL + 1            # trip/key packing base

to3006 = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)

counts = np.zeros(NBIN * NCELL, dtype=np.int64)
pf = pq.ParquetFile(SRC)
seen = 0

for batch in pf.iter_batches(batch_size=40000,
                             columns=["lon", "lat", "t_start", "t_end"]):
    lon_a = batch.column("lon")
    lat_a = batch.column("lat")
    off = np.asarray(lon_a.offsets)
    flon = np.asarray(lon_a.values)
    flat_ = np.asarray(lat_a.values)
    t0 = np.asarray(batch.column("t_start"))
    t1 = np.asarray(batch.column("t_end"))

    n = len(off) - 1
    npts = np.diff(off)
    keep = npts > 0
    if not keep.any():
        continue

    x, y = to3006.transform(flon, flat_)

    trip_of = np.repeat(np.arange(n), npts)
    start_of = np.repeat(off[:-1], npts)
    idx = np.arange(len(x)) - start_of
    denom = np.repeat(np.maximum(npts - 1, 1), npts)
    frac = idx / denom

    t = np.repeat(t0, npts) + frac * np.repeat(t1 - t0, npts)
    hb = np.floor(t / 3600.0).astype(np.int64) - H0
    np.clip(hb, 0, NBIN - 1, out=hb)

    ix = np.floor((x - X0) / CELL).astype(np.int64)
    iy = np.floor((y - Y0) / CELL).astype(np.int64)
    ok = (ix >= 0) & (ix < NX) & (iy >= 0) & (iy < NY)
    if not ok.any():
        continue

    cell = iy[ok] * NX + ix[ok]
    key = hb[ok] * NCELL + cell
    combo = (trip_of[ok] + seen).astype(np.int64) * BIG + key
    uniq = np.unique(combo)
    counts += np.bincount(uniq % BIG, minlength=NBIN * NCELL)

    seen += n
    print(f"  {seen:,} trips", flush=True)

mat = counts.reshape(NBIN, NCELL)
active = np.flatnonzero(mat.sum(axis=0) > 0)
print(f"\ncells ever loaded: {len(active):,}/{NCELL:,}")

iy, ix = np.divmod(active, NX)
cx = X0 + (ix + 0.5) * CELL
cy = Y0 + (iy + 0.5) * CELL
to4326 = Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)
clon, clat = to4326.transform(cx, cy)

sub = mat[:, active]
peak = int(sub.max())
print(f"peak cell load: {peak:,} trips in one hour")
print("busiest hours:",
      ", ".join(f"{H0+i:02d}:00={v:,}" for i, v in
                enumerate(sub.sum(axis=1)) if v > 0)[:300])

pos = np.column_stack([np.round(np.asarray(clon) * 1e5),
                       np.round(np.asarray(clat) * 1e5)]).astype(np.int32)
payload = {
    "cell_m": CELL,
    "nx": NX, "ny": NY,
    "hour0": H0,
    "nbin": NBIN,
    "ncell": int(len(active)),
    "peak": peak,
    "pos": base64.b64encode(pos.tobytes()).decode(),
    "counts": base64.b64encode(
        np.clip(sub, 0, 65535).astype(np.uint16).tobytes()).decode(),
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(payload, f, separators=(",", ":"))
print(f"wrote {OUT} ({os.path.getsize(OUT)/1e6:.2f} MB)")
