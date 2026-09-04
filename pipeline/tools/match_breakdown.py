
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
import pyarrow.parquet as pq
import pandas as pd

df = pq.read_table(os.path.join(DER, r"\trips_routed2.parquet".lstrip("\\")),
                   columns=["mode", "match", "n_pts"]).to_pandas()
tr = df[df["mode"].isin(["Train/Tram", "Bus", "Boat"])]
t = pd.crosstab(tr["mode"], tr["match"])
t["total"] = t.sum(axis=1)
real = t.get("osm_route", 0) + t.get("osm_network", 0)
t["network %"] = (100 * real / t["total"]).round(1)
print(t.to_string())
print("\nmedian vertices per trip, by mode:")
print(df.groupby("mode").n_pts.median().sort_values(ascending=False).to_string())

