"""Time-of-day profiles for the phone data, which itself has no time of day.

Three candidate sources, per speed-limit class, so the map can switch between
them and they can be compared:

  sthlm_fit   Trafikverket measured HOURLY traffic (Årstrafik, Stockholm only
              in the FlowSense package), median share per hour by speed limit,
              rescaled so its 06-18 / 18-22 / 22-06 totals match Göteborg's own
              2023 highway counts
  gbg3        Göteborg's own 2023 Trafikverket highway counts: only three
              periods (06-18, 18-22, 22-06), flat within each period
  synthetic   the synthetic population's own car timing (plausible car trips
              under way, 15-minute bins) - the same for every road

Every profile is a list of shares of the day's traffic that sum to 1; the page
multiplies a road's daily phone count by (share x bins per day).

Writes time_profiles.json
"""
import os, sys, json, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import FLOWSENSE, DER  # noqa: E402

import numpy as np
import pandas as pd
import geopandas as gpd
import pyogrio
import pyarrow.parquet as pq
from scipy.spatial import cKDTree

warnings.filterwarnings("ignore")
SPEED_CLASSES = [30, 40, 50, 60, 70, 80, 90, 100, 110, 120]     # as stage 23
PERIODS = {"06-18": range(6, 18), "18-22": range(18, 22), "22-06": list(range(22, 24)) + list(range(0, 6))}
MIN_LINKS = 10


def nearest_class(v):
    return int(np.argmin([abs(v - c) for c in SPEED_CLASSES]))


# ---------- Stockholm measured hourly shapes ----------
H = [f"Trafikflöde_{h:02d}_{h+1:02d}__fordon_dygn__alla_fordon" for h in range(24)]
st = pyogrio.read_dataframe(os.path.join(FLOWSENSE, r"ground_truth\ground_truth\raw\Arstrafik.gpkg"),
                            columns=H + ["Skyltad_hastighet", "Datum_för_start_av_perioden"],
                            read_geometry=False)
hv = st[H].apply(pd.to_numeric, errors="coerce")
# dates are plain YYYYMMDD integers; measurements reach back to the 1990s, so
# keep recent ones only
year = pd.to_datetime(st["Datum_för_start_av_perioden"].astype(str), format="%Y%m%d",
                      errors="coerce").dt.year
ok = hv.notna().all(axis=1) & (hv.sum(axis=1) > 0) & (year >= 2015)
share = hv[ok].div(hv[ok].sum(axis=1), axis=0).values
# the signposted-speed field is empty in this file, so Stockholm gives ONE
# hourly shape; per-class differences come from Göteborg's period split below
shape = np.median(share, axis=0); shape = shape / shape.sum()
sthlm = {c: shape for c in range(len(SPEED_CLASSES))}
years = year[ok]
print(f"Stockholm: {int(ok.sum()):,} links with hourly data measured {int(years.min())}-{int(years.max())} "
      f"(speed limits not recorded: one shape for all roads)")

# ---------- Göteborg 2023 period split (highway count links) ----------
gt = pyogrio.read_dataframe(os.path.join(FLOWSENSE,
      r"ground_truth\ground_truth\preprocessed\ground_truth_flows_cars_gbg_highway_2023.geojson")).to_crs(3006)
per = {}
for p in PERIODS:
    cols = [f"adt_{t}_{p.replace('-', '_')}" for t in ("latta_fordon", "medeltunga_fordon", "tunga_fordon")]
    per[p] = gt[cols].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)
per = pd.DataFrame(per)
per = per[per.notna().all(axis=1) & (per.sum(axis=1) > 0)]
per_share = per.div(per.sum(axis=1), axis=0)
# speed limit of each count link: nearest FlowSense (NVDB) segment
fs = gpd.read_parquet(os.path.join(DER, "flowsense_gbg.parquet"))
pts = np.array([[g.interpolate(0.5, normalized=True).x, g.interpolate(0.5, normalized=True).y] for g in fs.geometry])
tree = cKDTree(pts)
mid = gt.loc[per_share.index].geometry.force_2d().interpolate(0.5, normalized=True)
d, i = tree.query(np.column_stack([mid.x, mid.y]))
gcls = np.array([nearest_class(v) if np.isfinite(v) else nearest_class(70)
                 for v in fs.maxspeed.values[i]])
all_gbg = per_share.median().values.copy(); all_gbg /= all_gbg.sum()
gbg = {}
gbg_n = {}
for c in range(len(SPEED_CLASSES)):
    m = gcls == c
    gbg_n[SPEED_CLASSES[c]] = int(m.sum())
    v = per_share[m].median().values.copy() if m.sum() >= MIN_LINKS else all_gbg.copy()
    gbg[c] = v / v.sum()
print(f"Göteborg: {len(per_share)} highway count links with a period split; per class {gbg_n}; "
      f"overall day/evening/night = {np.round(all_gbg*100, 1).tolist()} %")

# ---------- build the three hourly (or 15-min) profiles ----------
def period_of(h):
    return next(p for p, hs in PERIODS.items() if h in hs)


out = {"speed_classes": SPEED_CLASSES, "profiles": {}}
fit, flat = {}, {}
for c in range(len(SPEED_CLASSES)):
    s = sthlm[c]; g = dict(zip(PERIODS, gbg[c]))
    f = np.array([s[h] * g[period_of(h)] / sum(s[k] for k in PERIODS[period_of(h)]) for h in range(24)])
    fit[c] = (f / f.sum()).round(6).tolist()
    fl_ = np.array([g[period_of(h)] / len(PERIODS[period_of(h)]) for h in range(24)])
    flat[c] = (fl_ / fl_.sum()).round(6).tolist()

# synthetic: plausible car trips under way per 15 minutes, 00:00-24:00
tr = pq.read_table(os.path.join(DER, "trips_final2.parquet"),
                   columns=["mode", "t_start", "t_end", "plausible"]).to_pandas()
tr = tr[tr.plausible & (tr["mode"] == "Car")]
a = np.clip((tr.t_start.values // 900).astype(int), 0, 95)
b = np.clip((tr.t_end.values // 900).astype(int), 0, 95)
diff = np.zeros(97)
np.add.at(diff, a, 1); np.add.at(diff, b + 1, -1)
syn = np.cumsum(diff)[:96]
syn = (syn / syn.sum()).round(6).tolist()

out["profiles"] = {
    "sthlm_fit": {"label": "Stockholm hourly, fitted", "bins": 24,
                  "by_class": [fit[c] for c in range(len(SPEED_CLASSES))],
                  "source": f"hourly shape from Trafikverket Årstrafik counts, Stockholm ({int(ok.sum()):,} links, "
                            f"measured {int(years.min())}–{int(years.max())}), rescaled per speed class to "
                            f"Göteborg's 2023 06–18 / 18–22 / 22–06 split"},
    "gbg3": {"label": "Göteborg, 3 periods", "bins": 24,
             "by_class": [flat[c] for c in range(len(SPEED_CLASSES))],
             "source": f"Trafikverket 2023 counts, Göteborg highway links ({len(per_share)}): "
                       f"06–18, 18–22 and 22–06 only"},
    "synthetic": {"label": "Synthetic rhythm", "bins": 96,
                  "by_class": [syn] * len(SPEED_CLASSES),
                  "source": "the synthetic population's own car trips under way, 15-minute bins"},
}
out["n_links"] = {"stockholm": int(ok.sum()), "goteborg_by_class": gbg_n}
p = os.path.join(DER, "time_profiles.json")
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def peak(prof, bins):
    v = np.asarray(prof); k = int(v.argmax()); m = 24 * 60 // bins
    return f"{k*m//60:02d}:{k*m%60:02d} ({v.max()*bins:.2f}x avg)"
c50, c70 = SPEED_CLASSES.index(50), SPEED_CLASSES.index(70)
for key, v in out["profiles"].items():
    print(f"{key:10s} peak, 50 km/h roads: {peak(v['by_class'][c50], v['bins'])} | "
          f"70 km/h roads: {peak(v['by_class'][c70], v['bins'])}")
print(f"wrote {p}")
