// deck.gl map: CARTO dark basemap + the corridors. The camera is controlled,
// so picking a corridor from the list can fly to it.
import { S } from "./state.js";
import * as C from "./corridors.js";

let dg = null, base = [];
export let onPick = () => {};
export const setPickHandler = fn => { onPick = fn; };

function tiles(){
  const { TileLayer, BitmapLayer } = deck;
  return new TileLayer({
    id:"basemap-tiles",
    data:"https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}@2x.png" +
         (S.cartoKey ? "?key=" + encodeURIComponent(S.cartoKey) : ""),
    minZoom:0, maxZoom:19, tileSize:256,
    renderSubLayers: props => {
      const bb = props.tile.boundingBox;
      return new BitmapLayer(props, {data:null, image:props.data,
        bounds:[bb[0][0], bb[0][1], bb[1][0], bb[1][1]]});
    }
  });
}

export function initMap(){
  base = [tiles()];
  dg = new deck.DeckGL({
    container:"map", viewState:S.view, controller:true,
    onViewStateChange: ({viewState}) => { S.view = viewState; render(); },
    getTooltip: info => C.tooltip(info),
    onClick: info => onPick(C.pick(info)),
    layers:[...base], style:{background:"#080D13"}
  });
}

export function render(){
  if(dg) dg.setProps({viewState:S.view, layers:[...base, ...C.layers()]});
}

// centre on a corridor without changing the zoom too much
export function flyTo(lon, lat){
  S.view = {...S.view, longitude:lon, latitude:lat, zoom:Math.max(S.view.zoom, 12.5),
            transitionDuration:700, transitionInterpolator:new deck.FlyToInterpolator()};
  render();
}
