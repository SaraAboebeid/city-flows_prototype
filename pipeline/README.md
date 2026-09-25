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
| 24 | `24_time_profiles.py` | time-of-day profiles per speed class — **no longer used by any dashboard**, see below | `time_profiles.json` |
| ~~25~~ | *removed* | the phone dashboard now takes everything from stage 30 | |
| 26 | `26_compare_corridors.py` | aggregates both sources to corridors (OSM street names) and compares them with each other and the 2023 counts | `corridors.csv`, `corridor_compare.json` |
| 27 | `27_export_corridors.py` | packs the corridors and their segment geometry for the corridor map | `../gothenburg-corridors-js/data/` |
| 28 | `28_prep_speed_sweep.py` | all nine FlowSense speed filters per road, the slow-traffic index and Poisson uncertainty | `flowsense_sweep.parquet`, `flowsense_sweep_roads.parquet` |
| 29 | `29_network_centrality.py` | betweenness centrality on the Trafikverket graph, and observed flow against it | `flowsense_centrality.parquet`, `flowsense_betweenness.parquet` (cache) |
| 30 | `30_export_phone_sweep.py` | packs the sweep, the uncertainty table and the residual for the phone dashboard | `../gothenburg-phone-js/data/sweep.json` |
| 31 | `31_street_design.py` | OSM lane counts and street class onto each phone road: traffic per lane, slow traffic by street type | `flowsense_street_design.parquet`, `street_design.json` |

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

**Time of day: dropped.** The phone dashboard used to borrow a daily rhythm so
the map could animate across a day. That was removed in September 2026: the
data has no time of day, no trip start and no trip end, and a running clock
implied otherwise however it was labelled. Stage 24 still computes the profiles
below and nothing consumes them — keep it if a future dataset brings real
hours, otherwise it can go.

The profiles it writes, for the record:

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

## Corridor comparison (stage 26)

Segment by segment the two sources barely agree (ρ 0.06), and both sides are
noisy there. Stage 26 tests whether aggregating to **corridors** — all segments
sharing an OSM street name, length-weighted so long corridors are not favoured
— recovers agreement. **It does not.** Across the 372 corridors the phones
observed well (≥ 20 sampled crossings, ≥ 400 m):

| | corridors | ρ synthetic vs phones | ρ vs 2023 counts |
|---|---|---|---|
| all well-observed corridors | 372 | −0.08 | synthetic 0.17 · phones 0.63 |
| only where the model has car traffic | 253 | +0.14 (+0.30 vs all-speed phones) | synthetic 0.19 · phones 0.59 |

Aggregation does not help because the disagreement is structural, not noise:

- **A third of the busiest corridors carry no synthetic traffic at all.** 119 of
  the 372 have zero synthetic car trips, including E6 south (Kungsbackaleden,
  25,710 counted vehicles/day), Gamla Riksvägen (29,836) and Ekenleden (23,832).
  This is scope, not a matching failure: motorways do carry synthetic traffic
  elsewhere (49% of motorway segments; E6 north peaks at 18,269 trips/day).
  Trips that leave the municipality are not in the source data.
- **Torslanda is over-loaded**, from the destination concentration above:
  Sörredsvägen takes 61.9‰ of synthetic vehicle-km against 1.5‰ of the phones',
  and Assar Gabrielssons Väg 16.9‰ against 0.9‰ (2,468 counted vehicles/day).
- **The main ring roads do agree**: Marieholmsleden 37‰ vs 38‰,
  Västerleden 74‰ vs 46‰, Dag Hammarskjöldsleden 17‰ vs 13‰.

Reading: the phones rank corridors much like the real counts (ρ ~0.6), the
synthetic model does not (ρ ~0.2), and that gap is the same at segment and
corridor level. The comparison therefore measures the model's scope — resident
trips only, 2019, no through traffic, freight or inbound commuters — rather
than a disagreement that better aggregation could resolve.

`corridors.csv` holds all 2,893 corridors with both sources' means, shares and
the log2 ratio, for inspection. Caveats: one OSM name can cover disjoint
streets, and 25% of phone segments sit on unnamed roads and are left out.

Stage 27 packs the result for **`../gothenburg-corridors-js/`**, a map of the
comparison (violet = the model misses the corridor, ember = it over-loads it).
The full method is written up in `../gothenburg-corridors-js/METHOD.md`.

## The speed sweep, uncertainty and network position (stages 28–30)

Three things the phone data can say on its own, without the synthetic model.

**Nine speed filters, not two.** FlowSense publishes a trajectory count per road
for every minimum average speed from 0 to 20 km/h in 2.5 steps. Each one is its
own random draw of 100,000 crossings from the trips that fast — they are *not*
nested subsets, so a road's count can rise as the filter tightens. Sweeping the
filter moves the map from all movement to motor traffic only, and the pattern
really does change: rank correlation with the all-speeds map falls from 0.72 at
≥ 5 km/h to 0.57 at ≥ 20 km/h, and the roads reached fall from 21,888 to 16,082.

The **slow-traffic index** (a road's share of the all-speeds draw ÷ its share of
the ≥ 20 km/h draw) reads as it should, which is the check that it means
anything:

| posted limit | 40 | 50 | 60 | 70 | 80 | 100 |
|---|---|---|---|---|---|---|
| median index | 2.50 | 2.17 | 1.33 | 0.55 | 0.26 | 0.20 |

Above 1 = relatively more slow traffic (walking, cycling); below = motor traffic.

**Sampling noise.** 100,000 crossings spread over 32,453 roads leaves most of
them thin: 25,123 roads (77%) carry fewer than 5 crossings, and the median
counted road has a relative standard error of 58%. Stage 28 stores exact
Poisson 95% intervals (4 crossings means 1.1–10.2), which the dashboard shows
in tooltips and uses to fade or hide roads too thin to rank.

**Network position.** Stage 29 builds the Trafikverket network shipped with
FlowSense as an undirected graph (56,339 nodes, 63,925 edges) and estimates
betweenness centrality from 400 sampled source nodes: shortest-path trees, then
every edge on the way back from each reachable node is credited. Observed flow
against centrality gives Spearman **0.53** across all roads the phones saw
(0.37 for the ≥ 20 km/h draw) — structure explains a good part of where traffic
is, but far from all of it. The mapped quantity is the rank difference (traffic
percentile − centrality percentile), which is unbiased for the well-observed
subset in a way a fitted residual is not; ember on the map is a road busier
than its position in the network predicts.

Betweenness takes ~3 minutes and is cached in `flowsense_betweenness.parquet`;
delete that file to recompute.

## Street size and street design (stage 31)

**Traffic per lane.** OpenStreetMap tags a width in metres on only 2% of
drivable roads, but a lane count on **71% of main roads** — and main roads are
where the phone sample is thick enough to trust anyway. Stage 31 reads the tags
straight from the Overpass tiles stage 11 cached (they kept every tag, so
nothing is re-downloaded), joins them to our segments by OSM way id, and snaps
each phone road onto a segment: 27,799 of 32,453 roads matched (86%), 8,446
with a lane count. Median sampled crossings per driving lane:

| motorway | trunk | motorway link | primary | secondary | tertiary |
|---|---|---|---|---|---|
| 14 | 13 | 11 | 8.5 | 5 | 4 |

Lane count against traffic is a weak ρ 0.24 — street size predicts far less
than you would expect, which is the interesting part.

**Slow traffic by street type**, using the slow index from stage 28:

| service | residential | tertiary | secondary | trunk | motorway |
|---|---|---|---|---|---|
| 5.00 | 2.50 | 2.16 | 1.80 | 0.33 | 0.31 |

**What could not be done: cycling and walking.** There is no mode in the phone
data, and worse, Göteborg maps its cycle network as *separate* ways
(`highway=cycleway`/`path`), while FlowSense's network is Trafikverket's road
network — every edge in it is labelled `unclassified`. Actual cycle
infrastructure is tagged on 0–1% of road ways (the common `cycleway:both` tag
on main roads almost always reads `no`), so only **33 of 7,330** well-observed
phone roads have any, 151 a sidewalk and 19 on-street parking. Far too few to
compare, so stage 31 records the coverage and draws no conclusion. The speed
filters remain a speed split, never a mode split: slow mixes walking, cycling
and congested driving.

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
