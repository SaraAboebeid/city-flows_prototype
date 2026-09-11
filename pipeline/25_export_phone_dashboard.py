"""Export the data for the phone-data dashboard (../gothenburg-phone-js/).

A separate dashboard from the synthetic population: it reads FlowSense only.
The phone payloads from stages 22-24 also carry synthetic-model fields (they
were built for a comparison); those are dropped here.

  phone.json          roads with sampled crossings, speed limits, count sites (stage 22)
  phone_views.json    per-direction roads + 100 m load grid                  (stage 23)
  time_profiles.json  time-of-day profiles per speed-limit class             (stage 24)

Anything else in data/ is removed. Also writes ../gothenburg-phone-js/config.json
with the CARTO basemap key from carto_api_key.txt (kept out of git).
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DER, PHONEWEB, carto_key  # noqa: E402

OUT = os.path.join(PHONEWEB, "data")
os.makedirs(OUT, exist_ok=True)

key = carto_key()
json.dump({"cartoApiKey": key}, open(os.path.join(PHONEWEB, "config.json"), "w"), indent=1)
print("basemap key: " + ("written to config.json" if key else
      "MISSING - paste your CARTO key into carto_api_key.txt and re-run"))


def load(name):
    return json.load(open(os.path.join(DER, name), encoding="utf-8"))


def dump(obj, name):
    json.dump(obj, open(os.path.join(OUT, name), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))


# ---- phone.json: phone fields only ----
ph = load("phone_payload.json")
gt = ph["stats"]["ground_truth"]
phone = {
    "n": ph["n"],
    "coords": ph["coords"], "npts": ph["npts"],
    "obs": ph["obs"], "obs20": ph["obs20"], "spd": ph["spd"],
    "ground": [{k: d[k] for k in ("lon", "lat", "adt", "phone", "src", "name")}
               for d in ph["ground"]],
    "stats": {
        "segments_observed": ph["stats"]["segments_observed"],
        "ground_truth": {g: {k: v for k, v in rows.items() if k.startswith("phone")}
                         for g, rows in gt.items()},
    },
}
dump(phone, "phone.json")

# ---- phone_views.json: unchanged ----
dump(load("phone_views.json"), "phone_views.json")

# ---- time_profiles.json: measured traffic rhythms only ----
tp = load("time_profiles.json")
tp["profiles"] = {k: v for k, v in tp["profiles"].items() if k in ("sthlm_fit", "gbg3")}
dump(tp, "time_profiles.json")

keep = {"phone.json", "phone_views.json", "time_profiles.json"}
for f in os.listdir(OUT):
    if f not in keep:
        os.remove(os.path.join(OUT, f))

tot = 0
for f in sorted(os.listdir(OUT)):
    sz = os.path.getsize(os.path.join(OUT, f)); tot += sz
    print(f"  {f:20s} {sz/1e6:6.2f} MB")
print(f"wrote {len(os.listdir(OUT))} files ({tot/1e6:.1f} MB) -> {OUT}")
