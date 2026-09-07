"""Does the dataset's own duration agree with its own route?

od_matrix carries two durations: calculated_duration (derived) and
sampled_duration (drawn from a distribution). The activity schedule uses one
of them; this checks which is consistent with the route geometry.
"""
import os, sys, glob, sqlite3, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA  # noqa: E402

import numpy as np
import pandas as pd

NUMS = re.compile(r"-?\d+\.?\d*")
TIME = re.compile(r"Start Time:\s*(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?),\s*"
                  r"End Time:\s*(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)")


def sweref_km(wkt):
    v = NUMS.findall(wkt or "")
    if len(v) < 4:
        return 0.0
    a = np.asarray(v, dtype=float)
    if a.size % 2:
        a = a[:-1]
    x, y = a[0::2], a[1::2]
    return float(np.hypot(np.diff(x), np.diff(y)).sum() / 1000)


rows = []
for p in sorted(glob.glob(os.path.join(DATA, "*.db")))[:12]:
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    for mode, route, cd, sd, ta in con.execute(
            "SELECT mode, route, calculated_duration, sampled_duration, "
            "transit_activity FROM od_matrix"):
        km = sweref_km(route)
        m = TIME.search(ta or "")
        sched = np.nan
        if m:
            t0 = int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
            t1 = int(m.group(4))*3600 + int(m.group(5))*60 + float(m.group(6))
            sched = (t1 - t0)/60 if t1 >= t0 else np.nan
        rows.append((mode, km, cd, sd, sched))
    con.close()

df = pd.DataFrame(rows, columns=["mode", "km", "calc_min", "samp_min",
                                 "sched_min"]).dropna(subset=["sched_min"])
print(f"{len(df):,} trips from 12 neighbourhood files\n")

print("=== which duration does the schedule actually use? ===")
d_calc = (df.sched_min - df.calc_min).abs()
d_samp = (df.sched_min - df.samp_min).abs()
print(f"  |schedule - calculated_duration|  median {d_calc.median():.2f} min")
print(f"  |schedule - sampled_duration|     median {d_samp.median():.2f} min")
print(f"  schedule matches sampled within 1 min: "
      f"{100*(d_samp < 1).mean():.1f}%")
print(f"  schedule matches calculated within 1 min: "
      f"{100*(d_calc < 1).mean():.1f}%")

print("\n=== implied speed, km/h (median) ===")
out = df.assign(
    v_sched=df.km/(df.sched_min/60),
    v_calc=df.km/(df.calc_min/60),
).replace([np.inf, -np.inf], np.nan)
print(out.groupby("mode")[["km", "v_sched", "v_calc"]].median()
      .round(1).sort_values("km", ascending=False).to_string())

w = out[out["mode"] == "Walking"]
print(f"\nWalking: median {w.km.median():.2f} km; "
      f"speed via schedule {w.v_sched.median():.1f} km/h, "
      f"via calculated_duration {w.v_calc.median():.1f} km/h")
print(f"walking trips over 5 km: {100*(w.km > 5).mean():.1f}%")
