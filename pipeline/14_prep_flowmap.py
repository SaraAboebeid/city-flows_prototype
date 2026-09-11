"""Pack street + transit flows into a compact payload for the flow-map page.

Two builds:
  standalone  15-minute time cube, larger budget
  artifact    hourly time cube, smaller budget (Artifact pages cap at 16 MB)

Every street segment with >= MIN_DAY plausible trips/day is shown in the
whole-day view. The time cube is filled busiest-segment-first until the byte
budget is spent; segments beyond it carry whole-day volumes only (they are
the quietest streets, near-invisible at 15-minute resolution anyway).

Binary blobs are gzip-compressed then base64'd; the page inflates them with
the browser's native DecompressionStream.
"""
import os, sys, json, gzip, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DER  # noqa: E402

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

MIN_DAY = 5
BUILDS = {"standalone": {"bin_min": 15, "budget_rows": 3_000_000},
          "artifact":   {"bin_min": 60, "budget_rows": 900_000}}
H0 = 3
MODES = ["Car", "Train/Tram", "Bus", "Bicycle/E-bike", "Walking", "Boat", "Other"]
STREET_MODES = ["Car", "Bicycle/E-bike", "Walking", "Other"]
SM_OF = {MODES.index(m): i for i, m in enumerate(STREET_MODES)}
DIMS = {"purpose": ["Home", "Work", "Leisure", "Grocery", "Pickup/Dropoff child",
                    "Education", "Shopping", "Travel", "Healthcare", "Other"],
        "age": ["16-24", "25-44", "45-64", "65+"],
        "sex": ["Women", "Men"],
        "status": ["Working", "Studying", "At home", "Other/Unknown"]}
TGROUPS = ["Train/Tram", "Bus", "Boat"]


def blob(arr):
    return base64.b64encode(gzip.compress(np.ascontiguousarray(arr).tobytes(), 9)).decode()


def pack_lines(lons, lats):
    """int32 first vertex + int16 deltas (1e-5 deg), densifying big jumps."""
    parts, npts = [], []
    for lo, la in zip(lons, lats):
        q = np.column_stack([np.round(np.asarray(lo) * 1e5),
                             np.round(np.asarray(la) * 1e5)]).astype(np.int64)
        while len(q) > 1:
            d = np.abs(np.diff(q, axis=0)).max(axis=1)
            bad = np.flatnonzero(d > 30000)
            if bad.size == 0:
                break
            q = np.insert(q, bad + 1, (q[bad] + q[bad + 1]) // 2, axis=0)
        parts.append(q[0].astype(np.int32).tobytes())
        parts.append(np.diff(q, axis=0).astype(np.int16).tobytes())
        npts.append(len(q))
    return b"".join(parts), np.asarray(npts, np.uint16)


# ---------- streets ----------
day = pq.read_table(os.path.join(DER, "street_flows_day.parquet")).to_pandas()
day = day[day.trips >= MIN_DAY].copy()
streets = pq.read_table(os.path.join(DER, "streets.parquet")).to_pandas()
streets = streets.set_index("edge_id").loc[day.edge_id]
order = np.argsort(day.trips.values, kind="stable")          # quiet first, busy on top
day = day.iloc[order].reset_index(drop=True)
streets = streets.iloc[order]
NS = len(day)
print(f"street segments shown: {NS:,} (>= {MIN_DAY} plausible trips/day)")

coords, npts = pack_lines(streets.lon.values, streets.lat.values)
bymode = np.column_stack([day[f"mode:{m}"].values for m in STREET_MODES]).astype(np.uint32)
tot = np.maximum(day.trips.values, 1)
shares, share_names = [], []
for d, vocab in DIMS.items():
    for v in vocab:
        shares.append(np.round(255 * day[f"{d}:{v}"].values / tot))
        share_names.append(f"{d}:{v}")
shares = np.column_stack(shares).clip(0, 255).astype(np.uint8)
city_share = {k: float(day[k].sum() / day.trips.sum()) for k in share_names}

hw = streets.highway.fillna("unclassified").values
hw_vocab = sorted(set(hw))
hw_idx = np.array([hw_vocab.index(h) for h in hw], np.uint8)
names = streets.name.fillna("").values
name_vocab = sorted(set(names))
name_lut = {n: i for i, n in enumerate(name_vocab)}
name_idx = np.array([name_lut[n] for n in names], np.uint32)

tcube = pq.read_table(os.path.join(DER, "street_flows_time.parquet")).to_pandas()
seg_pos = pd.Series(np.arange(NS), index=day.edge_id.values)
tcube = tcube[tcube.edge_id.isin(seg_pos.index)].copy()
tcube["seg"] = seg_pos.loc[tcube.edge_id].values
tcube["sm"] = tcube["mode"].map(SM_OF)
tcube = tcube.dropna(subset=["sm"])
tcube["sm"] = tcube["sm"].astype(int)

# ---------- transit ----------
tp = pq.read_table(os.path.join(DER, "transit_pieces.parquet")).to_pandas()
tday = pq.read_table(os.path.join(DER, "transit_flows_day.parquet")).to_pandas()
tday = tday[tday.trips >= MIN_DAY].sort_values("trips").reset_index(drop=True)
tp = tp.set_index("piece_id").loc[tday.piece_id]
t_coords, t_npts = pack_lines(tp.lon.values, tp.lat.values)
t_grp = np.array([TGROUPS.index(g) for g in tday.group], np.uint8)
ttime = pq.read_table(os.path.join(DER, "transit_flows_time.parquet")).to_pandas()
tpos = pd.Series(np.arange(len(tday)), index=tday.piece_id.values)
ttime = ttime[ttime.piece_id.isin(tpos.index)].copy()
ttime["p"] = tpos.loc[ttime.piece_id].values
print(f"transit pieces shown: {len(tday):,}")

# ---------- city-wide "trips under way" by mode (for the chart) ----------
tr = pq.read_table(os.path.join(DER, "trips_final2.parquet"),
                   columns=["mode", "t_start", "t_end", "plausible", "match"]).to_pandas()
tr = tr[tr.plausible]
tr["m"] = tr["mode"].map({m: i for i, m in enumerate(MODES)}).fillna(MODES.index("Other")).astype(int)


def city_profile(bin_min):
    bs = bin_min * 60
    nb = (24 - H0) * 60 // bin_min
    a = np.clip((tr.t_start.values // bs).astype(int) - H0 * 3600 // bs, 0, nb - 1)
    b = np.clip((tr.t_end.values // bs).astype(int) - H0 * 3600 // bs, 0, nb - 1)
    prof = np.zeros((len(MODES), nb + 1), np.int64)
    np.add.at(prof, (tr.m.values, a), 1)
    np.add.at(prof, (tr.m.values, b + 1), -1)
    return np.cumsum(prof, axis=1)[:, :nb].tolist()


# trips actually drawn, per mode: street modes use the dataset's own routes,
# transit only where the path was matched to the network
is_street = tr["match"] == "n/a"
is_tmatch = tr["match"].isin(["osm_route", "osm_network"])
mode_trips = {}
for m in STREET_MODES:
    mm = tr["mode"].isin([m]) if m != "Other" else ~tr["mode"].isin(MODES[:-1])
    mode_trips[m] = int((mm & is_street).sum())
for g in TGROUPS:
    mode_trips[g] = int(((tr["mode"] == g) & is_tmatch).sum())
print("trips drawn per mode:", mode_trips)

stats = json.load(open(os.path.join(DER, "street_flows_stats.json")))
anim = json.load(open(os.path.join(DER, "anim_stats.json")))

for name, cfg in BUILDS.items():
    per = cfg["bin_min"] // 15
    nb = (24 - H0) * 60 // cfg["bin_min"]
    tc = tcube.assign(b=tcube["bin"] // per).groupby(["seg", "sm", "b"], as_index=False).trips.sum()
    # busiest segments first until the row budget is spent
    rows_per_seg = tc.groupby("seg").size().reindex(np.arange(NS), fill_value=0)
    rank = np.argsort(-day.trips.values, kind="stable")
    cum = np.cumsum(rows_per_seg.values[rank])
    in_cube = np.zeros(NS, bool)
    in_cube[rank[cum <= cfg["budget_rows"]]] = True
    tc = tc[in_cube[tc.seg.values]].sort_values(["seg", "b", "sm"])
    counts = tc.groupby("seg").size().reindex(np.arange(NS), fill_value=0).values
    row_start = np.r_[0, np.cumsum(counts)].astype(np.uint32)
    key = (tc.b.values * len(STREET_MODES) + tc.sm.values).astype(np.uint16)
    val = tc.trips.values.clip(0, 65535).astype(np.uint16)
    cube_min = int(day.trips.values[in_cube].min()) if in_cube.any() else 0

    tt = ttime.assign(b=ttime["bin"] // per).groupby(["p", "b"], as_index=False).trips.sum()
    tt = tt.sort_values(["p", "b"])
    tcounts = tt.groupby("p").size().reindex(np.arange(len(tday)), fill_value=0).values

    payload = {
        "bin_min": cfg["bin_min"], "hour0": H0, "nbin": nb,
        "modes": MODES, "street_modes": STREET_MODES, "tgroups": TGROUPS,
        "share_names": share_names, "city_share": city_share,
        "mode_trips": mode_trips,
        "dims": DIMS, "hw_vocab": hw_vocab, "name_vocab": name_vocab,
        "stats": {**stats, "segments_shown": int(NS), "cube_segments": int(in_cube.sum()),
                  "cube_min_day": cube_min, "min_day": MIN_DAY,
                  "total_trips": anim["total_trips"],
                  "transit_pct": anim["transit_pct"]},
        "city_profile": city_profile(cfg["bin_min"]),
        "street": {"n": int(NS), "coords": blob(np.frombuffer(coords, np.uint8)),
                   "npts": blob(npts), "bymode": blob(bymode),
                   "shares": blob(shares), "hw": blob(hw_idx),
                   "name": blob(name_idx),
                   "row_start": blob(row_start), "key": blob(key), "val": blob(val)},
        "transit": {"n": int(len(tday)), "coords": blob(np.frombuffer(t_coords, np.uint8)),
                    "npts": blob(t_npts), "grp": blob(t_grp),
                    "day": blob(tday.trips.values.astype(np.uint32)),
                    "row_start": blob(np.r_[0, np.cumsum(tcounts)].astype(np.uint32)),
                    "bin": blob(tt.b.values.astype(np.uint8)),
                    "val": blob(tt.trips.values.clip(0, 65535).astype(np.uint16))},
    }
    out = os.path.join(DER, f"flow_payload_{name}.json")
    json.dump(payload, open(out, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"{name:10s} {cfg['bin_min']:>2}-min bins | time cube: {int(in_cube.sum()):,} "
          f"busiest segments (>= {cube_min} trips/day), {len(key):,} rows | "
          f"{os.path.getsize(out)/1e6:.2f} MB")
