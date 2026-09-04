"""Build both outputs from one template.

  gbg_day.html               Artifact build - CSP blocks raster tiles, so the
                             embedded vector basemap is used.
  gothenburg-day/index.html  self-hosted build - real CARTO tiles, vector
                             basemap dropped, wrapped as a complete document.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
import os, json

SCRATCH = HERE
DEST = WEB

read = lambda p: open(p, encoding="utf-8").read()
tpl = read(os.path.join(SCRATCH, "template.html"))
payload = read(os.path.join(DER, "anim_payload.json"))
basemap = read(os.path.join(DER, "basemap2.json"))
_lg = os.path.join(DER, "load_grid.json")
loadgrid = read(_lg) if os.path.exists(_lg) else "{}"
st = json.load(open(os.path.join(DER, "anim_stats.json"), encoding="utf-8"))

subtitle = (
    f"{st['total_trips']:,} trips made by a synthetic population of "
    f"{st['total_persons']:,} residents, replayed across one 2019 weekday. "
    f"A {st['sample']:,}-trip sample is drawn here, in proportion to how "
    f"each mode is actually used."
)


def note(tiles):
    credit = ("Basemap \u00a9 OpenStreetMap contributors \u00a9 CARTO."
              if tiles else "Basemap \u00a9 OpenStreetMap contributors.")
    return (
        "Car, cycling and walking trips follow the routed street paths supplied "
        "with the dataset. Tram, bus and ferry trips carry no geometry in the "
        "source, so they are matched onto OpenStreetMap transit lines \u2014 "
        f"{st['transit_pct']:.0f}% succeeded; the rest are drawn straight and "
        "should not be read as real paths.<br><br>"
        f"Coordinates SWEREF99 TM \u2192 WGS84. {credit}"
    )


def build(tiles):
    h = tpl.replace("__USE_TILES__", "true" if tiles else "false")
    h = h.replace("__SUBTITLE__", subtitle)
    h = h.replace("__NOTE__", note(tiles))
    h = h.replace("__PAYLOAD__", payload)
    # the tiled build never reads BASE, so ship {} instead of 1.6 MB
    h = h.replace("__BASEMAP__", "{}" if tiles else basemap)
    h = h.replace("__LOADGRID__", loadgrid)
    for tok in ("__PAYLOAD__", "__BASEMAP__", "__LOADGRID__", "__SUBTITLE__",
                "__NOTE__", "__USE_TILES__"):
        assert tok not in h, f"unreplaced {tok}"
    return h


art = build(tiles=False)
p1 = os.path.join(SCRATCH, "gbg_day.html")
open(p1, "w", encoding="utf-8", newline="\n").write(art)
print(f"artifact   {p1}  ({os.path.getsize(p1)/1e6:.2f} MB)  vector basemap")

full = build(tiles=True)
split = full.index('<div id="map">')
head, body = full[:split], full[split:]
doc = (
    '<!doctype html>\n<html lang="en">\n<head>\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
    '<meta name="description" content="An animated 24-hour replay of trips from '
    'the Gothenburg activity-based synthetic population.">\n'
    '<style>html{color-scheme:dark}body{margin:0}'
    'img{max-width:100%}[hidden]{display:none!important}</style>\n'
    + head + '</head>\n<body>\n' + body + '\n</body>\n</html>\n'
)
os.makedirs(DEST, exist_ok=True)
p2 = os.path.join(DEST, "index.html")
open(p2, "w", encoding="utf-8", newline="\n").write(doc)
for tag in ("<!doctype html>", "<head>", "</head>", "<body>", "</body>",
            "</html>", "<title>", "basemaps.cartocdn.com"):
    assert tag in doc, tag
print(f"standalone {p2}  ({os.path.getsize(p2)/1e6:.2f} MB)  CARTO raster tiles")
print("both builds verified")
