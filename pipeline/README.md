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

Re-running everything after new source data: 1 → 10 in order, then 11 → 14,
then 7 (page) and 16 (JS version). Stage 11 caches Overpass tiles in
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

## Outputs

- **`../gothenburg-day/index.html`** — the single-file page (animation, street
  load, street flows). About 19 MB, fully self-contained apart from deck.gl,
  fonts and CARTO tiles; open it directly or host it anywhere.
- **`../gothenburg-day-js/`** — the same page as a plain-JavaScript codebase (ES
  modules, data in separate files). Run `python serve.py` inside it; see
  `../gothenburg-day-js/README.md`.

`template.html` keeps a `USE_TILES` switch and vector-basemap fallback from an
earlier sandboxed build; `07_assemble.py` now always builds the tiled page.

**Basemap API key.** CARTO tiles need a free key (carto.com/basemaps/apikey),
otherwise they show an "API KEY REQUIRED" watermark. Paste it into
`../carto_api_key.txt` (or set the `CARTO_API_KEY` environment variable), then
re-run stages 7 and 16. The file is in `.gitignore`, but the key is embedded in
`gothenburg-day/index.html` and in `gothenburg-day-js/config.json` — restrict it
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
