# Göteborg corridors — synthetic model vs phone data

A map of Göteborg's traffic corridors, comparing the GAPSIM synthetic
population's car trips (2019) with FlowSense phone-based flows (2024) and the
2023 traffic counts. Built like the other two dashboards: plain ES modules, no
build step, deck.gl and IBM Plex from CDNs.

The method, and what the comparison found, is written up in
[METHOD.md](METHOD.md).

## Run it

```
cd gothenburg-corridors-js
python serve.py
```

Picks a free port from 8785 upwards, so it can run next to the other two
dashboards, and opens `http://127.0.0.1:<port>/`.

## What you are looking at

A **corridor** is every drivable segment carrying one OSM street name. Both
sources are averaged along it, weighted by segment length, so the number is
traffic *along the route*, not a total that rewards long corridors.

- **DIFFERENCE** (default): violet where the corridor takes a smaller share of
  the model's traffic than of the phones' — the model misses it — through grey
  where they agree, to ember where the model over-loads it. Fully violet also
  covers corridors where the model has no traffic at all. Line width is how
  much the phones saw there.
- **MODEL**: synthetic car trips per day.
- **PHONES**: sampled phone crossings (≥ 20 km/h).
- **Count sites 2023**: the white dots, with their measured vehicles per day.
- **Well-observed only**: the 372 corridors with at least 20 sampled crossings
  and 400 m of length. Everything else is drawn faint.

Click a corridor on the map or in the list to see its figures in the bottom
bar. Escape clears the selection.

## Files

| file | role |
|---|---|
| `index.html`, `css/style.css` | markup and styles |
| `js/main.js` | loads `data/corridors.json`, starts the map |
| `js/corridors.js` | decoding, colours, layers, legends, list, tooltips |
| `js/map.js` | deck.gl map, basemap, fly-to |
| `js/ui.js` | panel controls and selection |
| `js/decode.js`, `js/colors.js` | shared decoders and palettes |
| `data/corridors.json` | 2,893 corridors + their segments (stage 27) |

## Regenerating the data

```
python pipeline/26_compare_corridors.py     # the comparison  -> corridors.csv
python pipeline/27_export_corridors.py      # the map payload -> data/corridors.json
```

Stage 27 also writes `config.json` with the CARTO basemap key from
`carto_api_key.txt`. That file is kept out of git, but the key is readable by
anyone who opens the page, so restrict it to your domain before publishing.

## Credit

Somanath, S., Thuvander, L., Gil, J., Hollberg, A. (2024). Activity-based
simulations for neighbourhood planning towards social-spatial equity.
*Computers, Environment and Urban Systems* 111, 102242.
<https://doi.org/10.1016/j.compenvurbsys.2024.102242>

Teeuwen, R. & Gil, J. (2025). *FlowSense Traffic Flows — estimated from vehicle
trajectories based on sparse mobile phone geolocation data.* Zenodo.
<https://doi.org/10.5281/zenodo.16794871> (GPL-3.0).

Traffic counts: Trafikverket and Göteborg Stad (2023).
Basemap © OpenStreetMap contributors © CARTO.
