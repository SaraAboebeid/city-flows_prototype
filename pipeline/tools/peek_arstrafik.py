"""Trafikverket Årstrafik: coverage in Göteborg, years, and how varied the
hourly profiles are by speed limit."""
import os, sys, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import FLOWSENSE  # noqa: E402
import numpy as np, pandas as pd, pyogrio
warnings.filterwarnings("ignore")

p = os.path.join(FLOWSENSE, r"ground_truth\ground_truth\raw\Arstrafik.gpkg")
H = [f"Trafikflöde_{h:02d}_{h+1:02d}__fordon_dygn__alla_fordon" for h in range(24)]
cols = H + ["Trafikflöde__fordon_dygn__alla_fordon", "Skyltad_hastighet", "DIRECTION",
            "Riktningsuppdelad", "Datum_för_start_av_perioden", "Metod_för_datainsamling", "Namn"]
info = pyogrio.read_info(p)
print("crs:", info["crs"], "| features:", info["features"])
g = pyogrio.read_dataframe(p, columns=cols, bbox=(299000, 6383900, 335000, 6417300))
print(f"links in the Göteborg box: {len(g):,}")
hv = g[H].apply(pd.to_numeric, errors="coerce")
ok = hv.notna().all(axis=1) & (hv.sum(axis=1) > 0)
print(f"with a complete hourly profile: {int(ok.sum()):,}")
years = pd.to_datetime(g["Datum_för_start_av_perioden"], errors="coerce").dt.year
print("measurement start years:", years[ok].value_counts().sort_index().to_dict())
print("collection methods:", g.Metod_för_datainsamling[ok].value_counts().head(4).to_dict())
share = hv[ok].div(hv[ok].sum(axis=1), axis=0)
g2 = g[ok].assign(sp=pd.to_numeric(g.Skyltad_hastighet[ok], errors="coerce"))
print("\nmedian hourly share (%) by speed limit, selected hours:")
tab = share.groupby(g2.sp.values).median().loc[:, [H[3], H[7], H[12], H[16], H[22]]] * 100
tab.columns = ["03-04", "07-08", "12-13", "16-17", "22-23"]
tab["links"] = g2.groupby("sp").size()
print(tab.round(1).to_string())
print("\ndirection-split records:", g.Riktningsuppdelad[ok].value_counts().to_dict())
