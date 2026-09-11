"""Export the data for the JavaScript version (../gothenburg-day-js/).

The JavaScript version is the twin of gothenburg-day/index.html, so it reads
exactly the payloads the page embeds - just as separate files:

  anim.json        animation sample            (stage 6)
  loadgrid.json    100 m street-load grid      (stage 9)
  flows.json       street + transit flows      (stage 14, 15-minute cube)
  flowsample.json  trips re-traced on streets  (stage 15)
  meta.json        subtitle and caveat text shown on the page

Anything else in data/ is removed. Also writes ../gothenburg-day-js/config.json
with the CARTO basemap key from carto_api_key.txt (kept out of git).
"""
import os, sys, json, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DER, JSWEB, carto_key  # noqa: E402

OUT = os.path.join(JSWEB, "data")
os.makedirs(OUT, exist_ok=True)

key = carto_key()
json.dump({"cartoApiKey": key}, open(os.path.join(JSWEB, "config.json"), "w"), indent=1)
print("basemap key: " + ("written to config.json" if key else
      "MISSING - paste your CARTO key into carto_api_key.txt and re-run"))

FILES = {
    "anim.json": "anim_payload.json",
    "loadgrid.json": "load_grid.json",
    "flows.json": "flow_payload_standalone.json",
    "flowsample.json": "flow_sample.json",
}

keep = set(FILES) | {"meta.json"}
for f in os.listdir(OUT):
    if f not in keep:
        os.remove(os.path.join(OUT, f))

for dst, src in FILES.items():
    shutil.copyfile(os.path.join(DER, src), os.path.join(OUT, dst))

# the same text 07_assemble.py puts into the page
st = json.load(open(os.path.join(DER, "anim_stats.json"), encoding="utf-8"))
text = {
    "subtitle": (f"{st['total_trips']:,} trips made by a synthetic population of "
                 f"{st['total_persons']:,} residents, replayed across one 2019 weekday. "
                 f"A {st['sample']:,}-trip sample is drawn here, in proportion to how "
                 f"each mode is actually used."),
    "note": ("Car, cycling and walking trips follow the routed street paths supplied "
             "with the dataset. Tram, bus and ferry trips carry no geometry in the "
             "source, so they are matched onto OpenStreetMap transit lines — "
             f"{st['transit_pct']:.0f}% succeeded; the rest are drawn straight and "
             "should not be read as real paths.<br><br>"
             "Coordinates SWEREF99 TM → WGS84. "
             "Basemap © OpenStreetMap contributors © CARTO."),
}
json.dump(text, open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

tot = 0
for f in sorted(os.listdir(OUT)):
    sz = os.path.getsize(os.path.join(OUT, f)); tot += sz
    print(f"  {f:18s} {sz/1e6:6.2f} MB")
print(f"wrote {len(os.listdir(OUT))} files ({tot/1e6:.1f} MB) -> {OUT}")
