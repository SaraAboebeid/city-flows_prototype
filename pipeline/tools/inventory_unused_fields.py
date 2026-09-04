"""What's in the data that the visualisation doesn't use yet?"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
import sqlite3, glob
import pyarrow.parquet as pq
import pandas as pd

df = pq.read_table(f"{DER}\\trips_routed2.parquet",
                   columns=["purpose_from", "purpose_to", "neighborhood",
                            "mode", "t_start", "t_end"]).to_pandas()

print("=== trip purposes (destination) ===")
print(df.purpose_to.value_counts().head(12).to_string())
print(f"\ndistinct origin purposes: {df.purpose_from.nunique()}, "
      f"destination: {df.purpose_to.nunique()}")
print(f"neighborhoods: {df.neighborhood.nunique()}")

print("\n=== purpose x mode (share of trips to that purpose) ===")
top = df.purpose_to.value_counts().head(5).index
ct = pd.crosstab(df[df.purpose_to.isin(top)].purpose_to,
                 df[df.purpose_to.isin(top)]['mode'], normalize="index") * 100
print(ct.round(1)[["Car", "Walking", "Train/Tram", "Bus", "Bicycle/E-bike"]]
      .to_string())

print("\n=== person attributes available for joining ===")
p = glob.glob(os.path.join(DATA, "*.db"))[0]
con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
for col in ("age_group", "sex", "primary_status", "type_household"):
    vals = con.execute(
        f"SELECT {col}, COUNT(*) FROM person GROUP BY {col} "
        f"ORDER BY 2 DESC LIMIT 6").fetchall()
    print(f"  {col:16s} " + ", ".join(f"{v}({n})" for v, n in vals))
con.close()
