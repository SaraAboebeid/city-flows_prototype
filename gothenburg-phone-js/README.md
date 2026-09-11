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

- **Moving particles** (default): particles travel in each road's real
  direction of travel, in proportion to that direction's count. Direction and
  relative volume come from the data; timing and individual trips are
  illustrative.
- **STREET LOAD**: sampled crossings per 100 m cell, with dimmed particles on top.
- **STREET FLOWS**: grey width = sampled crossings per road, with particles on top.
- **COUNT SITES**: the 2023 Trafikverket and Göteborg Stad traffic counts
  (white dots). The panel shows how well the phone crossings rank roads against them.

Panel controls:

- **Sample**: *all speeds* (includes walking and cycling) or *≥ 20 km/h*
  (mostly motor traffic). The two samples are separate draws.
- **Time of day from**: the daily rhythm is borrowed from measured traffic, per
  speed-limit class. You can use Stockholm's hourly shape fitted to Göteborg's
  day/evening/night split, or Göteborg's own 3 periods, or no timing
  (whole-sample totals). The volumes are always the phones'.

## Run it

```
cd gothenburg-phone-js
python serve.py
```

It picks a port that is free on both IPv4 and IPv6, from 8775 upwards, so it
can run next to the synthetic dashboard. Then it opens `http://127.0.0.1:<port>/`.

## Basemap API key

This works the same way as in `gothenburg-day-js`. You need a `config.json`
next to `index.html` containing `{ "cartoApiKey": "your-key" }`.
`pipeline/25_export_phone_dashboard.py` writes it from `carto_api_key.txt`,
and git ignores it. The key is visible to anyone who opens the page, so
restrict it to your domain in the CARTO dashboard before publishing.

## Files

| file | role |
|---|---|
| `index.html`, `css/style.css` | markup and styles |
| `js/main.js` | loads `data/`, runs the clock |
| `js/state.js` | the shared state object |
| `js/phone.js` | the phone data: particles, load, flows, time-of-day profiles, panel text, tooltips |
| `js/map.js` | deck.gl map and basemap |
| `js/ui.js` | panel controls, bottom bar, daily-rhythm chart |
| `js/decode.js`, `js/colors.js` | decoders and palettes |
| `data/` | `phone.json`, `phone_views.json`, `time_profiles.json` |

## Regenerating the data

`data/` is written by `pipeline/25_export_phone_dashboard.py`. It reads the
outputs of stages 20–24 (see `pipeline/README.md`) and keeps only the phone
fields.

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
