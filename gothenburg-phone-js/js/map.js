// deck.gl map: CARTO dark basemap + the phone-data layers.
import { S } from "./state.js";
import * as phone from "./phone.js";

let dg = null, baseLayers = [];

function tiles(){
  const { TileLayer, BitmapLayer } = deck;
  return new TileLayer({
    id:"basemap-tiles",
    data:"https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}@2x.png" +
         (S.cartoKey ? "?key=" + encodeURIComponent(S.cartoKey) : ""),
    minZoom:0, maxZoom:19, tileSize:256,
    renderSubLayers: props => {
      const bb = props.tile.boundingBox;
      return new BitmapLayer(props, {
        data:null, image:props.data,
        bounds:[bb[0][0], bb[0][1], bb[1][0], bb[1][1]]
      });
    }
  });
}

export function initMap(){
  baseLayers = [tiles()];
  dg = new deck.DeckGL({
    container:"map",
    initialViewState:{longitude:11.968, latitude:57.706, zoom:10.6, pitch:0, bearing:0},
    controller:true,
    onViewStateChange: ({viewState}) => { S.zoom = viewState.zoom; return viewState; },
    getTooltip: info => phone.tooltip(info),
    layers:[...baseLayers],
    style:{background:"#080D13"}
  });
}

export function render(){
  dg.setProps({layers:[...baseLayers, ...phone.layers()]});
}
