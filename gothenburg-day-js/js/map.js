// deck.gl map: CARTO basemap, the trip animation, street load, street flows.
import { S, TRAIL } from "./state.js";
import { layerData } from "./trips.js";
import { loadLayer } from "./load.js";
import { flows, flowLayers, flowTooltip } from "./flows.js";

let dg = null;
let baseLayers = [];

export function initMap(){
  const { DeckGL, TileLayer, BitmapLayer } = deck;
  baseLayers = [
    new TileLayer({
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
    })
  ];
  dg = new DeckGL({
    container:"map",
    initialViewState:{longitude:11.968, latitude:57.706, zoom:10.6,
                      pitch:0, bearing:0},
    controller:true,
    getTooltip:flowTooltip,
    layers:[...baseLayers],
    style:{background:"#080D13"}
  });
}

function tripLayers(){
  const op = S.showLoad ? 0.34 : 0.86;
  return layerData.map(L => new deck.TripsLayer({
    id:"trips-"+L.name, data:L.data, getColor:L.color,
    opacity:op, widthMinPixels:1.7, jointRounded:true, capRounded:true,
    trailLength:TRAIL, currentTime:S.current, parameters:{depthTest:false}
  }));
}

export function render(){
  if(S.showFlows && flows){
    dg.setProps({layers:[...baseLayers, ...flowLayers()]});
    return;
  }
  const ll = loadLayer();
  dg.setProps({layers:[...baseLayers, ...(ll?[ll]:[]), ...tripLayers()]});
}
