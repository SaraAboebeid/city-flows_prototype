// Shared state for the whole app. Modules read and write S directly; the few
// cross-module calls go through `actions`, which main.js wires up, so no
// module has to import another in a circle.

export const S = {
  // animation sample (filled by main.js)
  PAY: null, M: 9, N: 0, meta: null, POS: null, TS: null, off: null, T0: 0, T1: 0,
  DIMS: null,

  // controls
  dim: "mode",
  on: null,          // { mode: Set, purpose: Set } - categories switched on
  filt: null,        // { age, sex, status } - { names, slot, sel: Set }
  current: 8 * 3600, // seconds since midnight
  playing: true,
  speed: 180,
  showLoad: false,
  plausOnly: false,
  showFlows: false,
  flowsWholeDay: false,

  cartoKey: "",      // basemap API key, from config.json
};

export const TRAIL = 780;

export const actions = {
  rebuild: () => {},   // filters / colour dimension changed
  render: () => {},    // redraw the map layers
  paint: () => {},     // redraw clock, counter and chart
};
