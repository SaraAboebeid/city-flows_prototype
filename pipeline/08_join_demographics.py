"""Join person attributes (age band, sex, main activity) onto every trip.

The od_matrix rows carry only uuid_person; age/sex/status live in the person
table of the same neighbourhood file, so the join is per-file and exact.

Writes trips_final.parquet
"""
import os, sys, glob, sqlite3, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER  # noqa: E402

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

SRC = os.path.join(DER, "trips_routed2.parquet")
OUT = os.path.join(DER, "trips_final.parquet")

AGE_BANDS = [(0, 15, "0-15"), (16, 24, "16-24"), (25, 44, "25-44"),
             (45, 64, "45-64"), (65, 200, "65+")]
SEX = {"Kvinnor": "Women", "Män": "Men"}
STATUS = {"WORK": "Working", "EDUCATION": "Studying", "HOME": "At home"}


def band(age_group, age):
    """age_group looks like '25-34 år'; fall back to the integer age."""
    n = None
    if age_group:
        m = re.match(r"\s*(\d+)", str(age_group))
        if m:
            n = int(m.group(1))
    if n is None and age is not None:
        try:
            n = int(age)
        except (TypeError, ValueError):
            n = None
    if n is None:
        return "Unknown"
    for lo, hi, label in AGE_BANDS:
        if lo <= n <= hi:
            return label
    return "Unknown"


people = {}
files = sorted(glob.glob(os.path.join(DATA, "*.db")))
for i, p in enumerate(files, 1):
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    for uid, ag, age, sex, st in con.execute(
            "SELECT uuid, age_group, age, sex, primary_status FROM person"):
        people[uid] = (band(ag, age),
                       SEX.get(sex, "Unknown"),
                       STATUS.get(st, "Other/Unknown"))
    con.close()
    if i % 20 == 0 or i == len(files):
        print(f"  {i}/{len(files)} files, {len(people):,} people", flush=True)

df = pq.read_table(SRC).to_pandas()
print(f"{len(df):,} trips loaded")

miss = ("Unknown", "Unknown", "Other/Unknown")
attrs = [people.get(u, miss) for u in df["person"].values]
df["age_band"] = pd.Categorical([a[0] for a in attrs])
df["sex"] = pd.Categorical([a[1] for a in attrs])
df["status"] = pd.Categorical([a[2] for a in attrs])

matched = (df["age_band"] != "Unknown").sum()
print(f"trips matched to a person record: {matched:,}/{len(df):,} "
      f"({100*matched/len(df):.1f}%)")

pq.write_table(pa.Table.from_pandas(df, preserve_index=False), OUT,
               compression="zstd")

for c in ("age_band", "sex", "status"):
    print(f"\n{c}:")
    print(df[c].value_counts().to_string())
print(f"\nwrote {OUT} ({os.path.getsize(OUT)/1e6:.0f} MB)")
