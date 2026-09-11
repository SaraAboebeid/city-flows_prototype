# Göteborg city-flows pipeline

Turns the Zenodo activity-based synthetic population for Göteborg into an
animated 24-hour movement map.

**Source data:** [Zenodo record 10801936](https://zenodo.org/records/10801936) —
*Activity based synthetic population of residents for Gothenburg, Sweden*,
94 SQLite files (4.48 GB), one per neighbourhood, each with `person`,
`household`, `house`, `building` and `od_matrix` tables.

Set `DATA` in [config.py](config.py) to wherever those `.db` files live.
Everything generated lands in `<DATA>/_derived`; the web build lands in
`../gothenburg-day`.

## Stages

Run in order. Stages 2–5 hit the network; 1, 3, 4 and 6 are CPU-bound.

| # | script | does | output |
|---|--------|------|--------|
| 1 | `01_extract_trips.py` | reads all 94 `.db`, parses trip times, reprojects SWEREF99 TM → WGS84 | `trips.parquet` (1,277,670 trips) |
| 2 | `02_fetch_transit_routes.py` | Overpass: tram/bus/ferry/train route relations, stitched to spines | `transit_routes.gpkg` (347 routes) |
| 3 | `03_match_transit_spines.py` | matches transit trips to a single route, cuts the sub-path | `trips_matched.parquet` |
| 4 | `04_route_transit_network.py` | routes the rest over the transit network as a graph (handles transfers) | `trips_routed*.parquet` |
| 5 | `05_fetch_basemap.py` | Overpass: water polygons, coastline, two road tiers | `basemap2.json` |
| 6 | `06_prep_animation.py` | samples trips, simplifies, packs to a binary payload | `anim_payload.json`, `anim_stats.json` |
| 7 | `07_assemble.py` | injects animation, load grid and street flows into `template.html` | `../gothenburg-day/index.html` |
| 8 | `08_join_demographics.py` | joins age band, sex, main activity from the `person` tables | `trips_final.parquet` |
| 9 | `09_street_load.py` | 100 m grid, 15-minute bins, all trips | `load_grid.json` |
| 10 | `10_flag_plausibility.py` | per-mode distance caps (`plausible` column) | `trips_final2.parquet` |
| 11 | `11_fetch_street_network.py` | Overpass: full OSM street network (roads, cycleways, footways), split at intersections | `streets.parquet` (313,274 segments, 15,081 km) |
| 12 | `12_assign_street_flows.py` | projects street trips onto segments: midpoint snaps for short route segments, A* junction-to-junction paths for long chords (mode-specific network) | `street_flows_day.parquet`, `street_flows_time.parquet` |
| 13 | `13_assign_transit_flows.py` | projects matched transit trips onto deduplicated transit pieces | `transit_flows_*.parquet` |
| 14 | `14_prep_flowmap.py` | packs flows (gzip blobs; 15-min cube for the busiest segments) | `flow_payload_*.json` |
| 15 | `15_retrace_flow_sample.py` | 40,000 trips re-traced along the OSM streets — the moving trips in STREET FLOWS | `flow_sample.json` |
| 16 | `16_export_js_version.py` | copies the page's payloads into the JavaScript version | `../gothenburg-day-js/data/` |
| 20 | `20_fetch_flowsense.py` | downloads FlowSense Traffic Flows (Zenodo 16794871), md5-checked, unzipped | `<FLOWSENSE>/` |
| 21 | `21_prep_flowsense.py` | Göteborg phone flows → undirected NVDB segments; 2023 counts → one table | `flowsense_gbg.parquet`, `groundtruth_gbg.parquet` |
| 22 | `22_compare_flowsense.py` | matches phone segments and counts to our streets; correlations; page payload | `phone_payload.json`, `phone_compare.json` |
| 23 | `23_prep_phone_views.py` | per-direction phone roads (moving particles) and the phone load grid on the synthetic 100 m grid | `phone_views.json` |
| 24 | `24_time_profiles.py` | time-of-day profiles per speed class (see *The phone dashboard over the day*) | `time_profiles.json` |
| 25 | `25_export_phone_dashboard.py` | copies the phone payloads, minus the synthetic-model fields, into the phone dashboard | `../gothenburg-phone-js/data/` |

Re-running everything after new source data: 1 → 10 in order, then 11 → 14,
then 7 (page) and 16 (JS version). The phone dashboard: 20 → 25 (stage 22 reads
the outputs of stages 11–12, and stage 24 reads stage 10's). Stage 11 caches Overpass tiles in
`<DATA>/_derived/osm_streets/`; delete that folder to refetch the network.

Stage 4 takes arguments so it can be re-run with a wider snap radius:

```
python 04_route_transit_network.py trips_routed.parquet trips_routed2.parquet 3000
```

## Street flows

The dataset's routes sit on OSM nodes (72% of vertices within 0.1 m of one),
but come from a *simplified* routing graph: long straight chords join
intersections and cut across curving streets. Stage 12 therefore re-traces
each chord along the real street (A* between the two junctions, on the drive /
bike / walk network matching the trip's mode). Result: **83.6% of route length
assigned** to a street segment, 127,667 segments carrying trips.

**Work destinations are heavily concentrated in the source** (verified in
`tools/check_destination_hotspots.py`): ~29% of all work trips end at the Volvo
Cars Torslanda site, one 250 m cell there receives 5.4% of every trip in the
city at just 5 distinct points, and single hypermarkets absorb tens of
thousands of grocery trips. This looks like destination choice weighted by
building capacity without a cap. It is why Torslandavägen (141,547 trips/day)
tops the flow map — faithful to the data, not to reality.

## Phone data (FlowSense)

**Data:** Teeuwen, R. & Gil, J. (2025). *FlowSense Traffic Flows — estimated
from vehicle trajectories based on sparse mobile phone geolocation data.*
Zenodo. <https://doi.org/10.5281/zenodo.16794871> (GPL-3.0). Method:
Teeuwen, R. & Gil, J. (2025). *Estimating traffic flows from vehicle
trajectories based on sparse mobile phone geolocation data.* NetMob 2025,
Book of Abstracts, pp. 129–130, Paris. Ground truth shipped with the dataset:
Trafikverket highway ADT and Göteborg Stad counts, 2023.

What the data is: phone location fixes (GPS, Wi-Fi or fused, per the authors'
extraction code) from 2024, chained into trips and map-matched to the
Trafikverket (NVDB) network. Trips are split into (trip, road) crossings and
**100,000 crossings are sampled at random per filter variant**; each road's
number is how many sampled trips crossed it, per direction of travel. So each
variant is its own draw (the ≥ 20 km/h count can exceed the all-speeds count
on a road), the all-speeds variant includes walking and cycling, and **no time
of day and no individual trips are published**. Two-way roads are stored per direction; stage 21
sums them. 26% of roads have any trajectory; the median non-zero road has 2.
So: rank comparisons only, and street-level comparison only where a road has
≥ 5 crossings (7,232 roads).

Results (Spearman ρ against the 2023 counts; `phone_compare.json`):

| | all 419 counts | highway links | municipal points |
|---|---|---|---|
| phones, ≥ 20 km/h | 0.71 | 0.81 | 0.56 |
| phones, all | 0.54 | 0.49 | 0.60 |
| synthetic car trips | 0.19 | 0.28 | 0.26 |

The phone flows reproduce the authors' result (very strong at highways with
the 20 km/h filter), which also checks our geometry matching. The synthetic
car flows agree weakly, and street by street they are essentially
uncorrelated with the phone flows (ρ 0.06 on the 7,232 well-observed roads;
within every speed class between −0.25 and 0.18). Evidence for why:

- **Scope.** The synthetic population is Göteborg residents only (2019): no
  inbound commuters, through traffic or freight. 23% of count sites — mostly
  motorways such as the E6 south and Rv 40 — get *no* synthetic car trips; the
  nearest street carrying any is a median 2.7 km away (`tools/diag_zero_and_roadclass.py`).
- **Big roads under-weighted.** Synthetic trips are 36% of counted traffic on
  streets under 2,000 vehicles/day but 5–9% on roads over 15,000.
- **Torslanda over-loaded** (Hisingsleden: 84,687 synthetic vs 12,840 counted),
  from the destination concentration above. Excluding it barely changes ρ.
- 8.7% of synthetic car-km lands on OSM paths — either the source routed some
  cars on paths, or stage 12's short-segment snapping picked a parallel path.

**The phone dashboard** (`../gothenburg-phone-js/`) is separate from the
synthetic population. The two sources differ in year, scope (residents only
vs everyone with a phone), unit (trips vs sampled crossings) and mode, so they
are not shown against each other. The dashboard uses the same style and encodings:
moving particles, STREET LOAD (crossings per cell on the same 100 m grid,
particles dimmed on top), STREET FLOWS (grey width per road plus particles),
and the 2023 count sites. Particles move in each road's real direction (the two
directions differ on 86.5% of roads; the busier takes a median 64%), in
proportion to the directional count: **direction and relative volume are
real, timing is illustrative**. Phones carry no mode, purpose or demographics,
so there is one colour. Stage 22 still computes the synthetic-vs-phone
statistics above; stage 25 leaves them out of the dashboard's data.

**The phone dashboard over the day.** The phone data has no time of day, so
its daily rhythm is borrowed from a switchable source (panel: *Time of day
from*) and applied per speed-limit class. The volumes stay the phones':

| source | what it is | caveat |
|---|---|---|
| Stockholm hourly, fitted | median hourly shape of 19,548 Trafikverket Årstrafik links measured 2015–2024, rescaled per class to Göteborg's 2023 06–18 / 18–22 / 22–06 split | Stockholm's hour-by-hour shape; the Stockholm file records no speed limits, so one shape for all classes |
| Göteborg 3 periods | Göteborg's own 2023 highway counts (131 links): day 77.9%, evening 14.3%, night 7.8% | only three steps a day, no rush-hour peaks |
| No timing | whole-sample totals | the clock does not change the map |

Stage 24 also writes a *synthetic rhythm* profile (the synthetic population's
car trips under way). Stage 25 drops it, because it would tie the phone data
back to the model. Göteborg's own hourly counts from Trafikverket (Lastkajen or
the open API) would be a better source, but they need a Trafikverket account
or API key.

## Outputs

- **`../gothenburg-day/index.html`** — the single-file page (animation, street
  load, street flows). About 19 MB, fully self-contained apart from deck.gl,
  fonts and CARTO tiles; open it directly or host it anywhere.
- **`../gothenburg-day-js/`** — the same page as a plain-JavaScript codebase (ES
  modules, data in separate files). Run `python serve.py` inside it; see
  `../gothenburg-day-js/README.md`.
- **`../gothenburg-phone-js/`** — the separate phone-data (FlowSense)
  dashboard, same style. Run `python serve.py` inside it; see
  `../gothenburg-phone-js/README.md`.

`template.html` keeps a `USE_TILES` switch and vector-basemap fallback from an
earlier sandboxed build; `07_assemble.py` now always builds the tiled page.

**Basemap API key.** CARTO tiles need a free key (carto.com/basemaps/apikey),
otherwise they show an "API KEY REQUIRED" watermark. Paste it into
`../carto_api_key.txt` (or set the `CARTO_API_KEY` environment variable), then
re-run stages 7, 16 and 25. The file is in `.gitignore`, but the key is embedded in
`gothenburg-day/index.html` and in the two dashboards' `config.json` — restrict it
to your domain in the CARTO dashboard before publishing, and think twice before
committing the built page.

## Trip durations are not consistent with trip routes

Verified in `tools/check_duration_fields.py` over 245,636 trips:

- The activity schedule uses **`sampled_duration`** — it matches within 1 minute
  **100%** of the time. `calculated_duration` matches only **1.9%**.
- `calculated_duration` is not mode-aware: it implies a flat **12.0 km/h** for
  car, bicycle, walking, taxi, moped and transportation service alike, and
  ~3.5 km/h for the transit modes. It is distance ÷ a constant.

So duration is drawn from a distribution and the route is generated separately;
the two are never reconciled. **Implied speeds are meaningless** — walking
reaches 1,198 km/h, car 1,881 km/h. Do not compute speed from this data.

Distance *is* a real property of the geometry, so `10_flag_plausibility.py`
caps distance per mode (`plausible` column, and the PLAUSIBLE ONLY button):

| mode | trips | median km | max km | cap | dropped |
|---|---|---|---|---|---|
| Walking | 225,787 | 1.59 | 34.87 | 5 | **75,825 (33.6%)** |
| Bicycle/E-bike | 137,319 | 4.64 | 38.69 | 25 | 409 (0.3%) |
| all others | — | — | ≤46 | 45–80 | 0 |

94.0% of trips pass. The problem is essentially confined to walking: mode looks
to be assigned largely independently of distance, so some long trips are
labelled Walking. Note these are also **visually over-represented** — a 20 km
walk draws 20 km of line while a typical 0.7 km walk is a dot.

## Known limits

- **Transit geometry is inferred.** The source has no route geometry for
  tram/bus/ferry, and never records which *line* a rider took. Matched paths are
  shortest paths over the network, not actual services. `match` column records
  provenance: `n/a` (dataset's own street routing — trustworthy), `osm_route`,
  `osm_network`, or `straight` (no match; do not read as a real path).
- **Boat effectively failed** (6.3%). OSM `route=ferry` near Göteborg is mostly
  long-haul crossings, not the Älvsnabben shuttles these trips represent.
- **Network is 2026, population is 2019.** Trams are stable; some bus routes moved.
- **Trip coverage is uneven** across neighbourhoods — Linnarhult has 78% of
  residents travelling, Bratthammar 0.4%. Check before per-area analysis.

## Tools

`tools/` holds the diagnostics used while building this — schema dumps, match-rate
breakdowns, basemap validation, an unused-field inventory, and a mojibake repair
for files damaged by a PowerShell UTF-8 round-trip.
