"""Build the self-hosted page gothenburg-day/index.html from template.html:
animation payload, street-load grid and street flows injected, CARTO tiles,
wrapped as a complete HTML document.

(The earlier Artifact build is retired: pages are delivered as local files,
and with street flows embedded the page is well past the Artifact size cap.)
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DER, WEB, HERE, TILE_URL, carto_key  # noqa: E402

read = lambda p: open(p, encoding="utf-8").read()
tpl = read(os.path.join(HERE, "template.html"))
payload = read(os.path.join(DER, "anim_payload.json"))
_lg = os.path.join(DER, "load_grid.json")
loadgrid = read(_lg) if os.path.exists(_lg) else "{}"
_fl = os.path.join(DER, "flow_payload_standalone.json")
flows = read(_fl) if os.path.exists(_fl) else "{}"
_fs = os.path.join(DER, "flow_sample.json")          # stage 15: trips on streets
flowsample = read(_fs) if os.path.exists(_fs) else "{}"
st = json.load(open(os.path.join(DER, "anim_stats.json"), encoding="utf-8"))

subtitle = (
    f"{st['total_trips']:,} trips made by a synthetic population of "
    f"{st['total_persons']:,} residents, replayed across one 2019 weekday. "
    f"A {st['sample']:,}-trip sample is drawn here, in proportion to how "
    f"each mode is actually used."
)
note = (
    "Car, cycling and walking trips follow the routed street paths supplied "
    "with the dataset. Tram, bus and ferry trips carry no geometry in the "
    "source, so they are matched onto OpenStreetMap transit lines — "
    f"{st['transit_pct']:.0f}% succeeded; the rest are drawn straight and "
    "should not be read as real paths.<br><br>"
    "Coordinates SWEREF99 TM → WGS84. "
    "Basemap © OpenStreetMap contributors © CARTO."
)

# CARTO tiles need an API key (carto_api_key.txt); without one they render with
# an "API KEY REQUIRED" watermark. Note the key ends up inside the page.
key = carto_key()
tile_url = TILE_URL + (f"?key={key}" if key else "")

h = (tpl.replace("__USE_TILES__", "true")
        .replace("__TILE_URL__", tile_url)
        .replace("__SUBTITLE__", subtitle)
        .replace("__NOTE__", note)
        .replace("__PAYLOAD__", payload)
        .replace("__BASEMAP__", "{}")          # tiles build never reads BASE
        .replace("__LOADGRID__", loadgrid)
        .replace("__FLOWS__", flows)
        .replace("__FLOWSAMPLE__", flowsample))
for tok in ("__PAYLOAD__", "__BASEMAP__", "__LOADGRID__", "__FLOWS__", "__FLOWSAMPLE__", "__TILE_URL__",
            "__SUBTITLE__", "__NOTE__", "__USE_TILES__"):
    assert tok not in h, f"unreplaced {tok}"

split = h.index('<div id="map">')
doc = (
    '<!doctype html>\n<html lang="en">\n<head>\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
    '<meta name="description" content="An animated 24-hour replay of trips from '
    'the Gothenburg activity-based synthetic population, with street flows.">\n'
    '<style>html{color-scheme:dark}body{margin:0}'
    'img{max-width:100%}[hidden]{display:none!important}</style>\n'
    + h[:split] + '</head>\n<body>\n' + h[split:] + '\n</body>\n</html>\n'
)
os.makedirs(WEB, exist_ok=True)
out = os.path.join(WEB, "index.html")
open(out, "w", encoding="utf-8", newline="\n").write(doc)
for tag in ("<!doctype html>", "<head>", "</head>", "<body>", "</body>",
            "</html>", "<title>", "basemaps.cartocdn.com"):
    assert tag in doc, tag
print(f"wrote {out}  ({os.path.getsize(out)/1e6:.2f} MB)"
      f"{'' if flows != '{}' else '  [no street flows found]'}")
print("basemap key: " + ("set" if key else
      "MISSING - paste your CARTO key into carto_api_key.txt and re-run"))
