"""Download the FlowSense Traffic Flows dataset (Zenodo 10.5281/zenodo.16794871).

Teeuwen, R. & Gil, J. (2025). FlowSense Traffic Flows - estimated from vehicle
trajectories based on sparse mobile phone geolocation data. Zenodo.
Accompanying paper: Teeuwen & Gil (2025), "Estimating traffic flows from
vehicle trajectories based on sparse mobile phone geolocation data",
NetMob 2025, Paris. Licence: GPL-3.0-or-later.

Files are md5-verified and unzipped into <FLOWSENSE>/.
"""
import os, sys, hashlib, zipfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import FLOWSENSE  # noqa: E402

import requests

RECORD = "https://zenodo.org/api/records/16794871"
FILE_URL = "https://zenodo.org/records/16794871/files/{name}?download=1"
# this record's files return 403 unless the user agent is a plain browser one
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
os.makedirs(FLOWSENSE, exist_ok=True)

rec = requests.get(RECORD, headers=HDR, timeout=60).json()
for f in rec["files"]:
    name, size = f["key"], f["size"]
    md5 = f["checksum"].split(":", 1)[1]
    out = os.path.join(FLOWSENSE, name)
    if not (os.path.exists(out) and os.path.getsize(out) == size):
        for attempt in range(3):
            try:
                with requests.get(FILE_URL.format(name=name), headers=HDR, stream=True,
                                  timeout=120) as r:
                    r.raise_for_status()
                    with open(out, "wb") as fh:
                        for chunk in r.iter_content(1 << 20):
                            fh.write(chunk)
                break
            except Exception as e:
                print(f"  {name} attempt {attempt+1}: {e}", flush=True)
                time.sleep(10)
    h = hashlib.md5()
    with open(out, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    ok = h.hexdigest() == md5
    print(f"{name:24s} {size/1e6:7.1f} MB  md5 {'OK' if ok else 'MISMATCH'}", flush=True)
    if not ok:
        raise SystemExit(f"checksum mismatch for {name}")
    dest = os.path.join(FLOWSENSE, os.path.splitext(name)[0])
    if not os.path.isdir(dest):
        with zipfile.ZipFile(out) as z:
            z.extractall(dest)
    print(f"  unzipped -> {dest}", flush=True)
print("done")
