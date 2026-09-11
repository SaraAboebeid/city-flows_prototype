# GAPSIM Göteborg — JavaScript version

The JavaScript twin of `gothenburg-day/index.html`: the same page, the same
look and behaviour (trip animation, street load, street flows with moving
trips, colour by mode or purpose, age / sex / activity filters, plausible-only),
built as plain ES modules with the data in separate files. No framework, no
build step; deck.gl and the IBM Plex fonts load from CDNs.

## Run it

```
cd gothenburg-day-js
python serve.py
```

It picks a port that is free on both IPv4 and IPv6 and opens
`http://127.0.0.1:<port>/`. (Always use `127.0.0.1`, not `localhost`: on
machines with Docker/WSL another service can hold the same port on IPv6.)
Browsers block data files opened straight from disk, so a server is needed.
To publish, copy the whole folder to any static host.

## Basemap API key

CARTO's basemap tiles now need a free API key (<https://carto.com/basemaps/apikey>);
without one every tile carries an "API KEY REQUIRED" watermark. Put the key in
`config.json` next to `index.html`:

```json
{ "cartoApiKey": "your-key" }
```

(`config.example.json` shows the format; `config.json` is kept out of git.)
Normally you don't edit it by hand: paste the key into `carto_api_key.txt` at
the project root and `pipeline/16_export_js_version.py` writes `config.json`.

The key is visible to anyone who opens the page — that is how browser tile
keys work. Before publishing, restrict it to your website's domain in the
CARTO dashboard.

## Files

| file | role |
|---|---|
| `index.html`, `css/style.css` | markup and styles — identical to the single-file page |
| `js/main.js` | loads `data/`, sets up state, runs the clock |
| `js/state.js` | the shared state object and the few cross-module actions |
| `js/decode.js` | base64 / gzip / polyline / trip-sample decoders |
| `js/trips.js` | the animation sample: filters, grouping, counts, chart series |
| `js/load.js` | STREET LOAD grid |
| `js/flows.js` | STREET FLOWS: volumes, share lens, moving re-traced trips, legend, tooltip |
| `js/map.js` | deck.gl map and layer order |
| `js/ui.js` | right-hand panel, bottom bar, stacked chart |
| `js/colors.js` | palettes |
| `data/` | `anim.json`, `loadgrid.json`, `flows.json`, `flowsample.json`, `meta.json` |

## Regenerating the data

`data/` is written by `pipeline/16_export_js_version.py`, which copies the
same payloads that `pipeline/07_assemble.py` embeds in the single-file page —
so the two versions always show the same thing. Run it after the pipeline
stages (see `pipeline/README.md`).

## Credit

Somanath, S., Thuvander, L., Gil, J., Hollberg, A. (2024). Activity-based
simulations for neighbourhood planning towards social-spatial equity.
*Computers, Environment and Urban Systems* 111, 102242.
<https://doi.org/10.1016/j.compenvurbsys.2024.102242>
