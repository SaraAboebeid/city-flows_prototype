// Shared state for the corridor comparison map.
export const S = {
  colorBy: "ratio",      // ratio (model vs phones) | syn | phone
  onlyWell: true,        // only corridors the phones observed well
  showCounts: true,      // 2023 traffic count sites
  selected: -1,          // corridor index, -1 = none
  view: {longitude:11.968, latitude:57.706, zoom:10.4, pitch:0, bearing:0},
  cartoKey: "",          // basemap API key, from config.json
};
