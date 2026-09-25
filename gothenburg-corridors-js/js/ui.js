// Panel, corridor list and the bottom bar.
import { S } from "./state.js";
import * as C from "./corridors.js";
import { render, flyTo, setPickHandler } from "./map.js";

const $ = id => document.getElementById(id);

export function refresh(){
  C.legend($("legend"));
  C.showNote($("showNote"));
  C.agreement($("agree"));
  C.list($("list"), select);
  C.detail($("dName"), $("dSub"), $("figures"));
}

export function select(i, fly = true){
  S.selected = (i === S.selected) ? -1 : i;
  const c = C.corridor(S.selected);
  if(c && fly && c.lon != null) flyTo(c.lon, c.lat);
  refresh(); render();
}

export function initUI(){
  document.querySelectorAll("#colorSeg button").forEach(b => b.addEventListener("click", () => {
    S.colorBy = b.dataset.c;
    document.querySelectorAll("#colorSeg button").forEach(o =>
      o.setAttribute("aria-pressed", String(o === b)));
    C.paint(); refresh(); render();
  }));
  document.querySelectorAll("#showChips .chip").forEach(b => b.addEventListener("click", () => {
    const k = b.dataset.k;
    if(k === "onlyWell"){ S.onlyWell = !S.onlyWell; C.paint(); }
    else S.showCounts = !S.showCounts;
    b.setAttribute("aria-pressed", String(k === "onlyWell" ? S.onlyWell : S.showCounts));
    refresh(); render();
  }));
  // clicking the map picks a corridor (or clears the selection)
  setPickHandler(i => select(i < 0 ? -1 : i, false));
  window.addEventListener("keydown", e => { if(e.key === "Escape") select(-1, false); });
}
