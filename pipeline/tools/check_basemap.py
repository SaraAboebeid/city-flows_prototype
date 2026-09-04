
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
import json, numpy as np

B = json.load(open(os.path.join(DER, r"\basemap.json".lstrip("\\")),
                   encoding="utf-8"))
for k, v in B.items():
    n = len(v)
    pts = sum(len(l) for l in v)
    flat = np.array([p for l in v for p in l], dtype=float)
    print(f"{k:7s} lines={n:>5,} pts={pts:>7,} "
          f"lon {flat[:,0].min():.3f}..{flat[:,0].max():.3f}  "
          f"lat {flat[:,1].min():.3f}..{flat[:,1].max():.3f}")
    print(f"        first line, first 3 pts: {v[0][:3]}")

# how much falls inside the visible city window?
win = (11.75, 12.15, 57.60, 57.80)
for k, v in B.items():
    inside = 0
    for l in v:
        a = np.array(l, dtype=float)
        if ((a[:,0] > win[0]) & (a[:,0] < win[1]) &
            (a[:,1] > win[2]) & (a[:,1] < win[3])).any():
            inside += 1
    print(f"{k:7s} lines touching city window: {inside:,}/{len(v):,}")
