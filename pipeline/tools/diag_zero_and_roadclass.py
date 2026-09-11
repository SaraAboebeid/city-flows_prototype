"""Are zero-synthetic count sites a matching error or real? And how is
synthetic car traffic spread over road classes (vehicle-km)?"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DER  # noqa: E402
import numpy as np, pandas as pd, pyarrow.parquet as pq
from pyproj import Transformer
from scipy.spatial import cKDTree

tf = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)
st = pq.read_table(os.path.join(DER, "streets.parquet"), columns=["edge_id", "highway", "length_m", "lon", "lat"])
day = pq.read_table(os.path.join(DER, "street_flows_day.parquet"), columns=["edge_id", "mode:Car"]).to_pandas()
car = np.zeros(st.num_rows); car[day.edge_id.values] = day["mode:Car"].values
hw = np.asarray(st.column("highway").to_pylist(), dtype=object)
L = np.asarray(st.column("length_m"))

vkm = pd.DataFrame({"hw": hw, "vkm": car * L / 1000, "km": L / 1000})
t = vkm.groupby("hw").agg(vkm=("vkm", "sum"), km=("km", "sum"))
t["share_vkm_%"] = 100 * t.vkm / t.vkm.sum()
print("synthetic car vehicle-km by OSM road class:")
print(t.sort_values("vkm", ascending=False).head(10).round(1).to_string())

# where zero-synthetic counts sit: nearest segment carrying any car trips
lo = st.column("lon").combine_chunks(); la = st.column("lat").combine_chunks()
off = np.asarray(lo.offsets)
X, Y = tf.transform(np.asarray(lo.values), np.asarray(la.values))
own = np.repeat(np.arange(st.num_rows), np.diff(off))
busy = car[own] > 0
tree_busy = cKDTree(np.column_stack([X[busy], Y[busy]]))
tree_any = cKDTree(np.column_stack([X, Y]))
P = json.load(open(os.path.join(DER, "phone_payload.json"), encoding="utf-8"))
g = pd.DataFrame(P["ground"])
z = g[g.syn == 0]
gx, gy = tf.transform(z.lon.values, z.lat.values)
d_any, i_any = tree_any.query(np.column_stack([gx, gy]))
d_busy, _ = tree_busy.query(np.column_stack([gx, gy]))
z = z.assign(nearest_street_m=d_any.round(0), nearest_car_street_m=d_busy.round(0),
             nearest_class=hw[own[i_any]])
print(f"\n{len(z)} count sites with zero synthetic car trips:")
print("  nearest OSM street class:", z.nearest_class.value_counts().head(6).to_dict())
print(f"  median distance to any street {z.nearest_street_m.median():.0f} m, "
      f"to a street carrying synthetic cars {z.nearest_car_street_m.median():.0f} m")
print(z.nlargest(8, "adt")[["src", "name", "adt", "nearest_class", "nearest_street_m",
                            "nearest_car_street_m", "lon", "lat"]].to_string(index=False))
mw = hw == "motorway"
print(f"\nmotorway segments with any synthetic car trip: {int((car[mw] > 0).sum()):,} of {int(mw.sum()):,}")
