// The right-hand panel, the bottom bar and the stacked chart.
import { S, actions } from "./state.js";
import { activeIdx, series, NB, countActive } from "./trips.js";
import { loadCells } from "./load.js";
import { flows, flowStreets, computeFlows } from "./flows.js";

let lastActive = 0;
export const refreshActive = () => { lastActive = countActive(); };

// ---------- panel ----------
const catsEl = () => document.getElementById("cats");

export function renderPanel(){
  const { meta, M, dim, on } = S;
  const D = S.DIMS[dim];
  const counts = new Map();
  for(const i of activeIdx){
    const nm = D.names[meta[i*M+D.slot]];
    counts.set(nm, (counts.get(nm)||0)+1);
  }
  const el = catsEl();
  el.innerHTML = "";
  D.names.forEach(name=>{
    if(!counts.has(name) && !on[dim].has(name)) return;
    const c = D.colors[name]||[200,200,200];
    const b = document.createElement("button");
    b.className = "cat";
    b.setAttribute("aria-pressed", on[dim].has(name) ? "true":"false");
    b.style.color = `rgb(${c.join(",")})`;
    b.innerHTML =
      `<span class="sw" style="background:rgb(${c.join(",")})"></span>`+
      `<span style="color:var(--ink)">${name}</span>`+
      `<span class="n">${(counts.get(name)||0).toLocaleString("en")}</span>`;
    b.addEventListener("click", ()=>{
      if(on[dim].has(name)) on[dim].delete(name); else on[dim].add(name);
      actions.rebuild(); actions.render();
    });
    el.appendChild(b);
  });
}

function chipRow(elId, key){
  const el = document.getElementById(elId), f = S.filt[key];
  el.innerHTML = "";
  f.names.forEach(name=>{
    const b = document.createElement("button");
    b.className = "chip";
    b.textContent = name;
    b.setAttribute("aria-pressed", f.sel.has(name) ? "true":"false");
    b.addEventListener("click", ()=>{
      if(f.sel.has(name)) f.sel.delete(name); else f.sel.add(name);
      b.setAttribute("aria-pressed", f.sel.has(name) ? "true":"false");
      actions.rebuild(); actions.render();
    });
    el.appendChild(b);
  });
}

// ---------- stacked chart ----------
let cvs, cx2;
export function drawChart(){
  const s = series(), D = S.DIMS[S.dim];
  const dpr = window.devicePixelRatio||1;
  const w = cvs.clientWidth, h = cvs.clientHeight;
  cvs.width = w*dpr; cvs.height = h*dpr;
  cx2.setTransform(dpr,0,0,dpr,0,0);
  cx2.clearRect(0,0,w,h);
  const bw = w/NB;
  const base = new Float64Array(NB);
  s.names.forEach((nm,k)=>{
    const c = D.colors[nm]||[200,200,200];
    cx2.fillStyle = `rgba(${c[0]},${c[1]},${c[2]},.72)`;
    cx2.beginPath();
    cx2.moveTo(0, h - (base[0]/s.max)*(h-4));
    for(let x=0;x<NB;x++){
      const y = h - ((base[x]+s.arr[k][x])/s.max)*(h-4);
      cx2.lineTo(x*bw, y); cx2.lineTo((x+1)*bw, y);
    }
    for(let x=NB-1;x>=0;x--){
      const y = h - (base[x]/s.max)*(h-4);
      cx2.lineTo((x+1)*bw, y); cx2.lineTo(x*bw, y);
    }
    cx2.closePath(); cx2.fill();
    for(let x=0;x<NB;x++) base[x]+=s.arr[k][x];
  });
  const f=(S.current-S.T0)/(S.T1-S.T0), px=f*w;
  cx2.strokeStyle="#DCE6F0"; cx2.lineWidth=1.2;
  cx2.beginPath(); cx2.moveTo(px,0); cx2.lineTo(px,h); cx2.stroke();
}

// ---------- clock ----------
export function paint(){
  const s=Math.floor(S.current)%86400;
  document.getElementById("clock").innerHTML =
    String(Math.floor(s/3600)).padStart(2,"0")+":"+
    String(Math.floor((s%3600)/60)).padStart(2,"0")+
    '<span class="z">CET</span>';
  document.getElementById("active").textContent = (S.showFlows && flows)
    ? flowStreets.toLocaleString("en")+" street segments carrying trips"+(S.flowsWholeDay?" · whole day":"")
    : lastActive.toLocaleString("en")+" trips moving";
  drawChart();
}

// ---------- controls ----------
export function initUI(){
  cvs = document.getElementById("chart");
  cx2 = cvs.getContext("2d");

  chipRow("fAge","age"); chipRow("fSex","sex"); chipRow("fStatus","status");

  document.querySelectorAll("#dimseg button").forEach(b=>{
    b.addEventListener("click", ()=>{
      S.dim = b.dataset.dim;
      document.querySelectorAll("#dimseg button").forEach(o=>
        o.setAttribute("aria-pressed", String(o===b)));
      document.getElementById("chartLabel").textContent =
        "Trips under way · by " + S.dim;
      actions.rebuild(); actions.render();
    });
  });

  cvs.addEventListener("click", e=>{
    const r=cvs.getBoundingClientRect();
    S.current = S.T0 + ((e.clientX-r.left)/r.width)*(S.T1-S.T0);
    actions.render(); paint();
  });

  document.getElementById("play").addEventListener("click", e=>{
    S.playing=!S.playing;
    e.currentTarget.textContent = S.playing?"PAUSE":"PLAY";
    e.currentTarget.setAttribute("aria-pressed", String(S.playing));
  });
  document.querySelectorAll(".spd").forEach(b=>{
    b.addEventListener("click", ()=>{
      S.speed=+b.dataset.s;
      document.querySelectorAll(".spd").forEach(o=>
        o.setAttribute("aria-pressed", String(o===b)));
    });
  });

  const lb = document.getElementById("loadBtn");
  if(!loadCells){ lb.disabled = true; lb.style.opacity = .4; }
  const fbtn = document.getElementById("flowBtn"), fday = document.getElementById("flowDayBtn");
  function setFlows(onFlag){
    S.showFlows = onFlag;
    fbtn.setAttribute("aria-pressed", String(S.showFlows));
    fday.hidden = !S.showFlows;
    document.getElementById("flowGroup").hidden = !S.showFlows;
    if(S.showFlows){ S.showLoad = false; lb.setAttribute("aria-pressed","false"); computeFlows(); }
    actions.render(); paint();
  }
  lb.addEventListener("click", ()=>{
    S.showLoad=!S.showLoad;
    lb.setAttribute("aria-pressed", String(S.showLoad));
    if(S.showLoad && S.showFlows){ setFlows(false); return; }
    actions.render();
  });
  fbtn.addEventListener("click", ()=> setFlows(!S.showFlows));
  fday.addEventListener("click", ()=>{
    S.flowsWholeDay = !S.flowsWholeDay;
    fday.setAttribute("aria-pressed", String(S.flowsWholeDay));
    computeFlows(); actions.render(); paint();
  });
  const pb = document.getElementById("plausBtn");
  pb.addEventListener("click", ()=>{
    S.plausOnly=!S.plausOnly;
    pb.setAttribute("aria-pressed", String(S.plausOnly));
    actions.rebuild(); refreshActive(); actions.render(); paint();
  });
  window.addEventListener("resize", drawChart);
}
