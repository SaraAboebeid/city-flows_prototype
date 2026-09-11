// Shared state for the phone-data dashboard.
export const S = {
  current: 8 * 3600,     // seconds since midnight
  playing: true,
  speed: 180,            // simulated seconds per real second
  layers: {              // map layers, each switched on and off on its own
    particles: true,     // moving particles
    flows: true,         // grey road widths
    load: false,         // 100 m cells
    counts: true,        // 2023 traffic count sites
  },
  sample: "all",         // all | v20  - FlowSense speed-filter sample
  timing: "sthlm_fit",   // sthlm_fit | gbg3 | none - where the daily rhythm comes from
  zoom: 10.6,            // current map zoom; line widths grow with it
  cartoKey: "",          // basemap API key, from config.json
};
