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
| 7 | `07_assemble.py` | injects payload into `template.html`, writes both builds | `gbg_day.html`, `../gothenburg-day/index.html` |

Stage 4 takes arguments so it can be re-run with a wider snap radius:

```
python 04_route_transit_network.py trips_routed.parquet trips_routed2.parquet 3000
```

## Two builds, one template

`07_assemble.py` produces both from `template.html` via a `USE_TILES` switch:

- **self-hosted** (`../gothenburg-day/index.html`) — real CARTO raster tiles.
  Host it anywhere; it is a single self-contained file.
- **Artifact** (`gbg_day.html`) — the Artifact sandbox blocks external tiles by
  CSP, so this build embeds vector water/road geometry instead.

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
