export const MODE_COLORS = {
  "Car":[255,138,61], "Train/Tram":[79,195,247], "Bus":[93,211,158],
  "Bicycle/E-bike":[255,209,102], "Walking":[240,106,155],
  "Boat":[126,232,250], "Other":[148,163,178]
};
export const PURPOSE_COLORS = {
  "Home":[242,180,65], "Work":[79,195,247], "Leisure":[240,106,155],
  "Grocery":[93,211,158], "Pickup/Dropoff child":[199,146,234],
  "Education":[126,232,250], "Shopping":[255,107,107],
  "Travel":[163,190,140], "Healthcare":[255,209,102], "Other":[148,163,178]
};

function lerpRamp(R, f){
  const x = Math.max(0, Math.min(1, f))*(R.length-1);
  const i = Math.floor(x), t = x-i;
  const a = R[i], b = R[Math.min(i+1, R.length-1)];
  return [a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t, a[2]+(b[2]-a[2])*t];
}

// traffic heat: violet -> magenta -> orange -> gold -> white hot
const RAMP = [[40,20,95],[120,30,150],[200,45,120],[245,95,65],
              [255,165,45],[255,225,110],[255,252,225]];
export const rampColor = f => lerpRamp(RAMP, f);

// volume: deep water -> teal -> straw -> cream (phone-observed flows)
const FRAMP = [[20,40,58],[30,84,112],[38,132,140],[96,176,140],
               [210,208,112],[255,220,130],[255,247,214]];
export const framp = f => lerpRamp(FRAMP, f);

// neutral slate -> pale steel, so coloured moving trips stand out on it
const NRAMP = [[36,50,64],[58,78,96],[92,114,134],[140,160,178],[200,212,224]];
export const nramp = f => lerpRamp(NRAMP, f);

// VOLUME: electric blue -> cyan -> mint -> white. Cool and bright, so it does
// not compete with the fire-coloured heat surface underneath.
const VRAMP = [[26,22,86],[30,84,200],[0,170,230],[90,235,205],[225,255,235]];
export const vramp = f => lerpRamp(VRAMP, f);

// PER LANE: neon emerald -> spring green -> acid lime -> white. The green band
// is the one hue the other scales leave free (volume is blue, heat and slow
// are violet/ember, network azure/magenta), so it never reads as one of those.
// it ends on neon yellow rather than white: white blows out the top of the
// scale and takes the glow with it
const LRAMP = [[0,110,125],[0,205,165],[90,242,120],[190,255,70],[255,240,50]];
export const lramp = f => lerpRamp(LRAMP, f);

// two-sided scales. SLOW and NETWORK are both two-sided but mean different
// things, so they get different pairs of colours rather than one palette.
function twoSided(under, over, mid){
  return t => {
    const c = t < 0 ? under : over, k = Math.min(1, Math.abs(t));
    return [mid[0]+(c[0]-mid[0])*k, mid[1]+(c[1]-mid[1])*k, mid[2]+(c[2]-mid[2])*k];
  };
}
// SLOW: fast traffic (violet) <- mixed -> slow movement (ember)
export const diverge = twoSided([110,123,255], [255,122,69], [62,74,90]);
// NETWORK: quieter than predicted (azure) <- as predicted -> busier (magenta)
export const divergeNet = twoSided([70,205,255], [255,74,170], [58,66,82]);
