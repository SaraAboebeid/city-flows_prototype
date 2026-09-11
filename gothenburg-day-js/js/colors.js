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

// street load
const RAMP = [[12,22,34],[26,58,88],[38,110,132],[92,168,140],
              [206,204,110],[255,214,120],[255,246,200]];
export const rampColor = f => lerpRamp(RAMP, f);

// neutral slate -> pale steel, so coloured moving trips stand out on it
const NRAMP = [[36,50,64],[58,78,96],[92,114,134],[140,160,178],[200,212,224]];
export const nramp = f => lerpRamp(NRAMP, f);

// share lens: under-represented (violet) <- city average -> over (ember)
const UNDER=[110,123,255], MIDC=[62,74,90], OVER=[255,122,69];
export function diverge(t){
  const c = t<0 ? UNDER : OVER, k = Math.min(1, Math.abs(t));
  return [MIDC[0]+(c[0]-MIDC[0])*k, MIDC[1]+(c[1]-MIDC[1])*k, MIDC[2]+(c[2]-MIDC[2])*k];
}
