// Shared state for the phone-data dashboard.
//
// There is no clock here on purpose: the FlowSense data carries no time of
// day, no trip start and no trip end. What it carries is how many sampled
// trips crossed each road, and in which direction.
export const S = {
  th: 0,                 // speed-filter index, 0 = all speeds .. 8 = >= 20 km/h
  sweeping: false,       // auto-sweep through the speed filters
  mode: "volume",        // the view: volume | slow | lane | net | heat
  showThin: true,        // draw roads with fewer than 5 crossings (faint)
  layers: {              // extras on top of the chosen view
    flows: true,         // what the view paints: the streets, or the heat surface
    particles: false,    // direction tokens, off by default: this is a still map
    counts: false,       // 2023 traffic count sites
  },
  zoom: 10.6,            // current map zoom; line widths grow with it
  cartoKey: "",          // basemap API key, from config.json
};
