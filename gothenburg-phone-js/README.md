# Göteborg phone flows — JavaScript dashboard

Traffic flows in Göteborg from mobile-phone location data (FlowSense, 2024),
in the same style as the synthetic-population dashboard (`gothenburg-day-js/`)
but separate from it. Plain ES modules with the data in separate files. No
framework, no build step; deck.gl and the IBM Plex fonts load from CDNs.

## What it shows

FlowSense chains phone location fixes (GPS, Wi-Fi or fused) into trips,
map-matches them to Trafikverket's road network, and splits them into
(trip, road) crossings. 100,000 crossings are sampled at random for each speed
filter, and each road counts how many sampled trips crossed it, per direction
of travel. The data has **no time of day and no individual trips**.

The map opens as a **still image**: a heat surface under the street network.
Each layer switches on and off on its own.

- **Traffic heat** (on by default): each road's crossings added to the 100 m
  grid cells it passes through, then blurred. The colour scale is relative to
  what is in view.
- **Street flows** (on by default): in VOLUME, width and colour = the raw
  sampled crossings per road at all speeds (`trajcount_minavgspeed0`), in six
  equal intervals from 1 to the busiest road (1–10 · 11–20 · … · 51–60; the
  busiest has 56); nothing divided or rescaled. The highest classes are drawn
  last.
- **Moving particles** (off by default): particles move along each directed
  road record, in proportion to that record's count. Direction and count come
  from the data; particle speed and timing are not in the data.
- **Count sites 2023** (off by default): the Trafikverket and Göteborg Stad
  traffic counts. The panel shows how well the phone crossings rank roads
  against them.

Panel controls:

- **Street flows show** (top of the panel): each colouring answers one question,
  printed under the buttons, and each has its own palette so they are never
  confused for one another.

  | button | question | colours |
  |---|---|---|
  | VOLUME | How many sampled trips crossed this road? | blue → cyan → mint → white |
  | SPEED | Is this road's share of the sampled trips bigger at all speeds or at ≥ 20 km/h? | violet (index below 1) ↔ ember (above 1) |
  | PER LANE | How many sampled trips crossed this road per driving lane? | teal → green → lime → yellow |
  | HEAT | Where do the sampled trips cross most often? | violet → magenta → orange → gold → white |
- **Speed filter**: a slider through the nine minimum-average-speed filters
  FlowSense publishes, from all speeds (0) to ≥ 20 km/h. It applies to the
  SPEED view only; VOLUME, PER LANE and HEAT always use all speeds. **SWEEP** steps through them automatically. Each filter is its own draw
  of 100,000 crossings from the trips with at least that average speed, not a
  subset of the one before, so a road's count can rise as the filter tightens.
- **Panels per view**: VOLUME, PER LANE and HEAT show only their legend; SPEED
  adds the speed filter and the meaning of its index. VOLUME, PER LANE and HEAT
  always use all speeds (`trajcount_minavgspeed0`). Every street view draws
  every road with a count. SPEED
  and PER LANE tooltips add a Poisson 95% interval, a statistical calculation
  that is not part of the FlowSense data.
**There is no clock, no timeline and no time-of-day control.** The data has no
time of day, no trip start and no trip end, so the dashboard offers none. The
bottom bar simply states what is on the map. (An earlier version could borrow a
daily rhythm from measured traffic counts; that was removed, because the only
honest answer is that the phone data cannot say when anything happened.)

A view can be shared as a link: `#mode=lane&th=8&layers=flows,counts` opens with
that colouring, that speed filter and those layers.

## What the extra layers mean

- **Speed**: a road's share of the all-speeds draw divided by its share of the
  ≥ 20 km/h draw. Ember = above 1, violet = below 1. Median 2.50 on 40 km/h
  streets, 0.20 on 100 km/h roads. The data has no travel mode.
- **Per lane**: sampled crossings divided by the number of driving lanes, so a
  four-lane road must carry four times as much to look as loaded as a one-lane
  street. Lane counts come from OpenStreetMap: 71% of main roads have one, few
  residential streets do, and roads without one are drawn grey. Median per lane
  runs from 14 on motorways to 4 on tertiary streets.

## Run it

```
cd gothenburg-phone-js
node serve.js
```

Everything in this folder is JavaScript — the page, the modules and the little
static server. It picks a port that is free on both IPv4 and IPv6, from 8775
upwards, so it can run next to the other dashboards, then opens
`http://127.0.0.1:<port>/`. (The Python pipeline that *builds* the data lives in
`../pipeline`; nothing here needs it at run time.)

## Basemap API key

You need a `config.json` next to `index.html` containing
`{ "cartoApiKey": "your-key" }`. `pipeline/30_export_phone_sweep.py` writes it
from `carto_api_key.txt`, and git ignores it. The key is visible to anyone who opens the page, so
restrict it to your domain in the CARTO dashboard before publishing.

## Files

| file | role |
|---|---|
| `index.html`, `css/style.css` | markup and styles |
| `img/chalmers-next-labs-white.png` | the Chalmers Next Labs logo (official white version, cropped and resized from `CNL_new_logo_white.png`) |
| `js/main.js` | loads `data/`, runs the clock |
| `js/state.js` | the shared state object |
| `js/phone.js` | the phone data: particles, load, flows, time-of-day profiles, panel text, tooltips |
| `js/map.js` | deck.gl map and basemap |
| `js/ui.js` | panel controls and the bottom summary bar |
| `serve.js` | the local static server (Node, no dependencies) |
| `js/decode.js`, `js/colors.js` | decoders and palettes |
| `data/` | `sweep.json` — roads, the nine filters, the heat grid, uncertainty, count sites; `nvdb.json` — each road's RLID with its NVDB street name, road number, speed limit and road manager (stage 32, optional) |

## Regenerating the data

```
python pipeline/28_prep_speed_sweep.py       # the nine filters, slow index, uncertainty
python pipeline/29_network_centrality.py     # betweenness (~3 min, then cached)
python pipeline/31_street_design.py          # OSM lane counts and street class
python pipeline/30_export_phone_sweep.py     # -> data/sweep.json + config.json
```

Stages 20, 21, 22 and 24 produce their inputs; see `pipeline/README.md`.

## Credit

Teeuwen, R. & Gil, J. (2025). *FlowSense Traffic Flows — estimated from vehicle
trajectories based on sparse mobile phone geolocation data.* Zenodo.
<https://doi.org/10.5281/zenodo.16794871> (GPL-3.0).

Method: Teeuwen, R. & Gil, J. (2025). *Estimating traffic flows from vehicle
trajectories based on sparse mobile phone geolocation data.* NetMob 2025 Book
of Abstracts, pp. 129–130.

Traffic counts: Trafikverket and Göteborg Stad (2023). Time-of-day shape:
Stockholm stad traffic counts (Årstrafik). Basemap © OpenStreetMap
contributors © CARTO.
