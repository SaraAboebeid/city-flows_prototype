# Corridor comparison — what was done, step by step

Comparing the GAPSIM synthetic population (Somanath et al., 2019 reference
year) with FlowSense phone-based traffic flows (Teeuwen & Gil, 2024), using the
2023 Trafikverket and Göteborg Stad counts as a neutral yardstick.

Everything below is reproducible from `pipeline/`. Stage numbers refer to the
scripts in that folder.

---

## 0. Why aggregate at all

Segment by segment the two sources barely agree: Spearman ρ 0.06 across the
7,232 roads the phones observed well (stage 22). Both sides are noisy at that
resolution:

- the median phone road carries only 2–3 sampled crossings, because FlowSense
  publishes a random sample of 100,000 (trip, road) crossings for the whole
  city, not a census;
- one routing decision in the synthetic data moves a trip to a parallel street,
  so a segment's count can swing while the corridor's total does not.

Aggregating cancels both kinds of noise. If the two sources describe the same
city, agreement should rise sharply with aggregation. That is the test.

## 1. The unit: a corridor

A **corridor** is every drivable OSM segment carrying one street name —
"Lundbyleden", "Dag Hammarskjöldsleden". Names come from `streets.parquet`
(stage 11). Non-drivable classes (footway, path, cycleway, steps, track,
service-only types) are excluded, as in stage 22.

Of 313,274 OSM segments, 172,127 are drivable and 99,194 of those are named.

**Caveat:** one OSM name can cover disjoint streets in different parts of the
city; they are treated as one corridor. Splitting by connectivity would be the
refinement.

## 2. Putting both sources on that unit

**Synthetic side** — direct. Stage 12 already assigns each synthetic car trip
to OSM segments (83.6% of route length assigned), so `street_flows_day.parquet`
gives `mode:Car` trips per day per segment. Those segments carry the name
already, so the corridor is just a group-by.

**Phone side** — needs matching, because FlowSense sits on Trafikverket's NVDB
network, not OSM. Reusing stage 22's geometry matching:

1. build a KD-tree of points every ~2 m along every drivable OSM segment
   (4,617,097 points);
2. sample each of the 63,925 phone road segments every 10 m (598,735 points
   total) and snap each sample to the nearest OSM point within **8 m**;
3. give each phone segment the street name it snapped to most often, requiring
   at least **half** its samples to agree, so a segment straddling two streets
   is dropped rather than misfiled.

Result: 92.6% of sample points snapped, and 48,098 of 63,925 phone segments
(75%) landed on a named corridor. The missing quarter sit on unnamed roads.

**Counts** — the 419 sites. A line-geometry site (Trafikverket highway link)
gets the modal name along it, exactly as above. A point site (Göteborg Stad) is
assigned to the *busiest* drivable segment within **25 m**, because a counter
sits on the main road, not on the side street beside it. 344 of 419 placed.

## 3. The quantity compared

Both sides are averaged **weighted by segment length**:

```
corridor value = Σ (flow_i × length_i) / Σ length_i
```

This is "how much traffic along this route", so a corridor is not rewarded for
being chopped into many segments, nor for being long.

The two sources share no unit — the model counts trips per day, the phones
count sampled crossings — so the comparison never uses raw magnitudes. It uses:

- **ranks** (Spearman ρ), and
- **shares**: each corridor's per-mille of the city total of flow × length.

The map's DIFFERENCE colour is `log2(model share / phone share)`: 0 means the
corridor takes the same slice of each source, +1 means the model puts twice as
large a slice there, −1 half. It saturates at ±4 (a 16× difference).

**Filters:** a corridor must be at least 400 m long to count as a route, and is
called *well observed* when the phones sampled at least 20 crossings on it. 372
of 2,893 corridors qualify.

## 4. What came out

| | corridors | model vs phones | model vs counts | phones vs counts |
|---|---|---|---|---|
| well-observed corridors | 372 | **−0.08** | 0.17 | 0.63 |
| only where the model has traffic | 253 | **+0.14** | 0.19 | 0.59 |
| *(segment level, stage 22)* | 7,232 | *0.12* | *0.19* | *0.71* |

**Aggregation did not help.** Corridor-level agreement between model and phones
is no better than segment level — slightly worse. Meanwhile the phones track
the real counts at ρ ≈ 0.6 either way, so the matching and the aggregation are
sound; it is the two sources that disagree.

Three structural reasons, all visible on the map:

1. **A third of the busiest corridors carry no synthetic traffic at all** —
   119 of the 372. They include E6 south (Kungsbackaleden, 25,710 counted
   vehicles/day), Gamla Riksvägen (29,836) and Ekenleden (23,832). This is
   scope, not a matching failure: 49% of motorway segments do carry synthetic
   traffic, and E6 north peaks at 18,269 trips/day. Trips that leave the
   municipality are simply not in the source data, so the roads that carry them
   are empty. These are the fully violet corridors.
2. **Torslanda is over-loaded**, following the destination concentration
   already documented in the pipeline README (~29% of work trips end at the
   Volvo Cars site). Sörredsvägen takes 61.9‰ of the model's vehicle-km against
   1.5‰ of the phones', and Assar Gabrielssons Väg 16.9‰ against 0.9‰ on a road
   counted at 2,468 vehicles/day. These are the ember corridors on Hisingen.
3. **The main ring roads agree well**: Marieholmsleden 37‰ vs 38‰, Västerleden
   74‰ vs 46‰, Dag Hammarskjöldsleden 17‰ vs 13‰. Where the model's trip
   universe matches reality, it performs.

**Reading:** the comparison measures the synthetic model's *scope* — residents
only, 2019, no through traffic, freight or inbound commuters — rather than a
disagreement that finer method could fix. The phone data is the better proxy
for total traffic; the model is the only source that carries who travels and
why.

## 5. The scripts

| stage | script | does | output |
|---|---|---|---|
| 26 | `26_compare_corridors.py` | everything in sections 1–4 | `corridors.csv`, `corridor_compare.json` |
| 27 | `27_export_corridors.py` | packs corridors + their segment geometry for the map | `gothenburg-corridors-js/data/corridors.json`, `config.json` |

Prerequisites: stages 11–12 (street network and synthetic flow assignment),
21 (FlowSense prepared), 22 (segment-level comparison, for the reference
numbers). Run:

```
python pipeline/26_compare_corridors.py
python pipeline/27_export_corridors.py
cd gothenburg-corridors-js && python serve.py
```

`corridors.csv` holds all 2,893 corridors — both sources' means, shares, the
log2 ratio, count ADT — for inspection in Excel or QGIS.

## 6. The map

`corridors.json` is 1.7 MB: 67,680 segment geometries in the project's usual
polyline encoding (int32 first vertex, int16 deltas at 1e-5°, gzipped and
base64), an index per segment naming its corridor, and one record per corridor
with both sources' values. The page colours whole corridors, because that is
the level at which the comparison holds — a per-segment colour would imply a
precision the data does not have.

## 7. What would sharpen this

- **Screenlines**: count both sources across the river crossings and the ring.
  The classic transport-planning validation, and immune to routing noise.
- **Calibration rather than verdict**: a per-corridor "the model sees x% of
  real traffic here" table, usable as a correction factor by road class.
- **Split same-named corridors** by connectivity, and give unnamed roads
  synthetic corridor ids so the missing 25% of phone segments come back in.
