// Store Monitor tab: live state from Atlas, history from the Historian (via server.py /api/monitor/*).
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const TZ = "America/Chicago";
  const HOUR = 3600e3;

  // State categories (status palette - always shown with a label; faults also carry a hatch for colour-blind readers)
  const CAT = {
    normal: {label: "Running normally", color: "#1F8A47"},
    idle: {label: "Off / standby", color: "#86C29C"},
    routine: {label: "Planned cycle", color: "#4F86D4"},
    alert: {label: "Attention", color: "#E39A00"},
    fault: {label: "Fault", color: "#C8261A", hatch: true},
    nodata: {label: "No data", color: "#DDD7CB"},
  };
  const CAT_ORDER = ["normal", "idle", "routine", "alert", "fault", "nodata"];
  const SERIES = ["#2a78d6", "#eb6834", "#1baf7a"];   // categorical slots 1-3 (validated all-pairs)
  const COND = {0: ["Healthy", "ok"], 1: ["Warning", "warn"], 2: ["Danger", "bad"], 3: ["Fault", "bad"]};
  const SHORT = {COOLER: "Cooler", FREEZER: "Freezer", HVAC: "HVAC", GENERATOR: "Generator", SOFTSERVE: "Soft serve"};
  const WARN_Z = 2.2, DANGER_Z = 3.4;   // health index 70 / 40 (see Atlas HealthIndexOf)

  function category(cls, code) {
    if (code == null) return "nodata";
    if (code >= 40) return "fault";
    switch (cls) {
      case "COOLER": case "FREEZER": return code === 10 || code === 20 ? "normal" : code === 0 ? "idle" : "routine";
      case "HVAC": return [10, 20, 21, 22].includes(code) ? "normal" : "idle";
      case "GENERATOR": return code === 0 ? "idle" : code === 10 ? "routine" : "alert";
      case "SOFTSERVE": return code === 0 ? "normal" : "routine";
    }
    return "normal";
  }

  // ---------- state ----------
  let catalog = null, storeById = {}, classByCode = {}, current = null, curIdx = {}, fleetData = null;
  let unitData = {}, loadingFleet = false, fleetSeq = 0, unitSeq = 0;
  const S = {scope: "store", store: "AR-20031", terr: "", fleet: [], eq: ["COOLER", "FREEZER", "HVAC", "GENERATOR", "SOFTSERVE"],
    hours: 72, focus: null, cmp: []};
  try { const f = JSON.parse(localStorage.getItem("monitor.fleet") || "[]"); if (Array.isArray(f)) S.fleet = f; } catch (e) { /* no storage */ }
  const saveFleet = () => { try { localStorage.setItem("monitor.fleet", JSON.stringify(S.fleet)); } catch (e) { /* ignore */ } };

  // ---------- formatting ----------
  const fmt1 = (n) => (n == null ? "–" : (Math.round(n * 10) / 10).toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 1}));
  const fmt0 = (n) => (n == null ? "–" : Math.round(n).toLocaleString());
  const usd = (n) => (n == null ? "–" : "$" + Math.round(n).toLocaleString());
  function dur(ms) {
    if (ms == null) return "–";
    const m = Math.round(ms / 60000);
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    if (h < 48) return `${h}h ${m % 60}m`;
    return `${Math.floor(h / 24)}d ${h % 24}h`;
  }
  const dtf = new Intl.DateTimeFormat("en-US", {timeZone: TZ, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
  const when = (ms) => dtf.format(new Date(ms));
  const hourF = new Intl.DateTimeFormat("en-US", {timeZone: TZ, hour: "numeric"});
  const dayF = new Intl.DateTimeFormat("en-US", {timeZone: TZ, weekday: "short", day: "numeric"});
  const localHourF = new Intl.DateTimeFormat("en-US", {timeZone: TZ, hour: "numeric", hourCycle: "h23"});
  const tickCache = new Map();
  const storeName = (id) => { const s = storeById[id]; return s ? `${id} · ${s.city}` : id; };
  const stateLabel = (cls, code) => (code == null ? "No data" : (classByCode[cls]?.states?.[code] ?? `State ${code}`));
  const unitKey = (store, cls) => `${store}|${cls}`;

  // ---------- URL ----------
  function readHash() {
    const h = location.hash.replace(/^#/, "");
    if (!h.startsWith("monitor")) return false;
    const p = new URLSearchParams(h.slice(8));
    if (["store", "terr", "fleet", "all"].includes(p.get("scope"))) S.scope = p.get("scope");
    if (p.get("store")) S.store = p.get("store");
    if (p.get("terr")) S.terr = p.get("terr");
    if (p.get("eq")) S.eq = p.get("eq").split(",").filter((c) => SHORT[c]);
    if ([6, 24, 72, 168].includes(+p.get("h"))) S.hours = +p.get("h");
    if (p.get("focus")) { const [st, cl] = p.get("focus").split("."); S.focus = {store: st, cls: cl}; }
    S.cmp = p.get("cmp") ? p.get("cmp").split(",") : [];
    return true;
  }
  function writeHash() {
    const p = new URLSearchParams({scope: S.scope, h: S.hours, eq: S.eq.join(",")});
    if (S.scope === "store") p.set("store", S.store);
    if (S.scope === "terr") p.set("terr", S.terr);
    if (S.focus) p.set("focus", `${S.focus.store}.${S.focus.cls}`);
    if (S.cmp.length) p.set("cmp", S.cmp.join(","));
    history.replaceState(null, "", "#monitor?" + p.toString());
  }

  function scopeStores() {
    if (!catalog) return [];
    if (S.scope === "store") return catalog.stores.filter((s) => s.id === S.store);
    if (S.scope === "terr") return catalog.stores.filter((s) => s.territory === S.terr);
    if (S.scope === "fleet") return catalog.stores.filter((s) => S.fleet.includes(s.id));
    return catalog.stores;
  }
  const scopeClasses = () => catalog.classes.filter((c) => S.eq.includes(c.code));

  // ---------- fetch ----------
  async function getJSON(url) {
    const r = await fetch(url);
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }
  function showErr(msg) { const e = $("m-err"); e.textContent = msg || ""; e.style.display = msg ? "block" : "none"; }

  async function loadCurrent() {
    try {
      current = await getJSON("/api/monitor/current");
      curIdx = {};
      for (const u of current.units) curIdx[unitKey(u.store, u.cls)] = u;
      $("m-updated").textContent = `Live from Atlas · ${new Date(current.generatedAt).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})}`;
      showErr("");
      renderNow(); renderKpis(); renderFocusHead();
    } catch (e) { showErr(`Couldn't read live values from Atlas: ${e.message}`); }
  }

  async function loadFleet() {
    const stores = scopeStores();
    if (!stores.length || !S.eq.length) { fleetData = null; renderHistory(); return; }
    const seq = ++fleetSeq;
    const qs = new URLSearchParams({hours: S.hours, classes: S.eq.join(",")});
    if (S.scope !== "all") qs.set("stores", stores.map((s) => s.id).join(","));
    $("m-history").classList.add("stale");
    try {
      const j = await getJSON("/api/monitor/fleet?" + qs);
      if (seq !== fleetSeq) return;
      if (j.loading) {
        $("m-hist-note").textContent = j.error ? `Historian: ${j.error}` : `Loading 7 days of history from the Historian… ${Math.round(100 * j.progress)}%`;
        setTimeout(loadFleet, 3000);
        return;
      }
      fleetData = j;
      $("m-hist-note").textContent = "";
      renderHistory(); renderKpis();
    } catch (e) { showErr(`Couldn't read history: ${e.message}`); }
    finally { if (seq === fleetSeq) $("m-history").classList.remove("stale"); }
  }

  async function loadUnits() {
    if (!S.focus) return;
    const seq = ++unitSeq;
    const list = [S.focus.store, ...S.cmp].map((st) => ({store: st, cls: S.focus.cls}));
    $("m-focus").classList.add("stale");
    try {
      const res = await Promise.all(list.map((u) => getJSON(`/api/monitor/unit?store=${encodeURIComponent(u.store)}&cls=${u.cls}&hours=${S.hours}`)));
      if (seq !== unitSeq) return;
      unitData = {};
      for (const r of res) unitData[unitKey(r.store, r.cls)] = r;
      renderFocus();
    } catch (e) { showErr(`Couldn't read the unit's history: ${e.message}`); }
    finally { if (seq === unitSeq) $("m-focus").classList.remove("stale"); }
  }

  // ---------- controls ----------
  function renderControls() {
    document.querySelectorAll("#m-scope button").forEach((b) => b.classList.toggle("on", b.dataset.scope === S.scope));
    $("m-store-wrap").hidden = S.scope !== "store";
    $("m-terr-wrap").hidden = S.scope !== "terr";
    $("m-fleet-wrap").hidden = S.scope !== "fleet";
    $("m-store").value = S.store;
    $("m-terr").value = S.terr;
    document.querySelectorAll("#m-eq button").forEach((b) => { b.classList.toggle("on", S.eq.includes(b.dataset.cls)); b.setAttribute("aria-pressed", S.eq.includes(b.dataset.cls)); });
    document.querySelectorAll("#m-range button").forEach((b) => b.classList.toggle("on", +b.dataset.h === S.hours));
    $("m-fleet-chips").innerHTML = S.fleet.length
      ? S.fleet.map((id) => `<span class="mchip">${esc(storeName(id))}<button type="button" data-rm="${esc(id)}" aria-label="Remove ${esc(id)}">×</button></span>`).join("")
      : `<span class="hint">Your fleet is empty. Add stores by ID or city, add a whole territory, or use ☆ on any store below.</span>`;
    const n = scopeStores().length;
    $("m-scope-sum").textContent = S.scope === "store" ? "" : `${n} store${n === 1 ? "" : "s"}`;
  }

  function changed({fleet = true, units = false} = {}) {
    writeHash(); renderControls(); renderNow(); renderKpis();
    if (fleet) loadFleet();
    if (units) loadUnits();
  }

  function setFocus(store, cls, scroll = true) {
    if (S.focus && S.focus.cls !== cls) S.cmp = [];
    S.cmp = S.cmp.filter((s) => s !== store);
    S.focus = {store, cls};
    writeHash(); renderFocusHead(); loadUnits(); renderNow();
    if (scroll) $("m-focus").scrollIntoView({behavior: "smooth", block: "start"});
  }
  window.monitorFocus = setFocus;

  function toggleFleet(id) {
    S.fleet = S.fleet.includes(id) ? S.fleet.filter((x) => x !== id) : [...S.fleet, id].sort();
    saveFleet();
    changed({fleet: S.scope === "fleet"});
  }

  // ---------- KPIs ----------
  function renderKpis() {
    if (!current || !catalog) return;
    const ids = new Set(scopeStores().map((s) => s.id));
    const units = current.units.filter((u) => ids.has(u.store) && S.eq.includes(u.cls));
    const faults = units.filter((u) => u.cond === 3);
    const danger = units.filter((u) => u.cond === 2), warn = units.filter((u) => u.cond === 1);
    const scored = units.filter((u) => u.health != null).sort((a, b) => a.health - b.health);
    const low = scored[0];
    const exposure = units.reduce((a, u) => a + (u.exposure || 0), 0);
    const now = Date.now();
    const longest = faults.map((u) => ({u, d: u.since ? now - Date.parse(u.since) : 0})).sort((a, b) => b.d - a.d)[0];
    let faultShare = null;
    if (fleetData) {
      let tot = 0, bad = 0;
      for (const fu of fleetData.units) {
        if (!ids.has(fu.store) || !S.eq.includes(fu.cls)) continue;
        const r = fu.states;
        tot += (r.length ? r[0][0] : fleetData.end) - fleetData.start;
        for (let i = 0; i < r.length; i++) {
          const t1 = i + 1 < r.length ? r[i + 1][0] : fleetData.end, d = t1 - r[i][0];
          tot += d;
          if (category(fu.cls, r[i][1]) === "fault") bad += d;
        }
      }
      faultShare = tot ? (100 * bad) / tot : null;
    }
    const tile = (cls, label, value, note) => `<div class="kpi ${cls}"><div class="label">${label}</div><div class="value">${value}</div><div class="note">${note}</div></div>`;
    $("m-kpis").innerHTML = [
      tile("", "Units monitored", fmt0(units.length), `${ids.size} store${ids.size === 1 ? "" : "s"} · ${S.eq.length} equipment type${S.eq.length === 1 ? "" : "s"}`),
      tile("k-bad", "Faults now", fmt0(faults.length), longest ? `Longest: ${esc(SHORT[longest.u.cls])} at ${esc(storeName(longest.u.store))}, ${dur(longest.d)}` : "No unit is in a fault state"),
      tile("k-warn", "Drifting, not yet reported", fmt0(danger.length + warn.length), `${danger.length} danger · ${warn.length} warning. Health has dropped but the unit hasn't faulted`),
      tile("", "Lowest health", low ? fmt1(low.health) : "–", low ? `${esc(SHORT[low.cls])} at ${esc(storeName(low.store))}` : "No health-scored units in scope"),
      tile("k-usd", "Product at risk", usd(exposure), "From drifting units: product at risk × urgency"),
      tile("", `Time in fault, last ${rangeLabel()}`, faultShare == null ? "…" : `${fmt1(faultShare)}%`, "Share of unit-hours in any fault state"),
    ].join("");
  }
  const rangeLabel = () => ({6: "6 h", 24: "24 h", 72: "3 days", 168: "7 days"})[S.hours];

  // ---------- Now ----------
  function statePill(cls, u) {
    const c = category(cls, u?.state);
    return `<span class="spill"><i class="sw ${c}"></i>${esc(stateLabel(cls, u?.state))}</span>`;
  }
  function healthBadge(u) {
    if (!u || u.health == null) return "";
    const band = u.health < 40 ? "bad" : u.health < 70 ? "warn" : "ok";
    return `<span class="hb ${band}" title="Health index">${fmt1(u.health)}</span>`;
  }
  function condBadge(u) {
    if (!u || u.cond == null || u.cond === 0) return "";
    const [label, cls] = COND[u.cond];
    return `<span class="pill ${cls}">${u.cond === 3 ? "⛔" : "⚠"} ${label}</span>`;
  }
  function unitWorst(storeId) {
    let w = 1000;
    for (const c of S.eq) {
      const u = curIdx[unitKey(storeId, c)];
      if (!u) continue;
      if (u.cond === 3) w = Math.min(w, -10);
      else if (u.health != null) w = Math.min(w, u.health - (u.cond || 0) * 5);
    }
    return w;
  }

  function renderNow() {
    if (!catalog) return;
    const stores = scopeStores(), classes = scopeClasses();
    const box = $("m-now");
    if (!stores.length) { box.innerHTML = `<div class="card empty">No stores in this scope yet.</div>`; return; }
    if (!classes.length) { box.innerHTML = `<div class="card empty">Pick at least one equipment type above.</div>`; return; }
    if (!current) { box.innerHTML = `<div class="card empty">Reading live values from Atlas…</div>`; return; }
    if (S.scope === "store") {
      const s = stores[0];
      box.innerHTML = `<div class="store-head card"><div><h3>${esc(s.city)} <span class="muted">· ${esc(s.id)}</span></h3>
          <div class="muted">${esc(s.address)}, ${esc(s.city)} ${esc(s.zip)} · ${esc(s.territory)} · ${s.open ? "Open" : esc(s.status === "TEMP_CLOSED" ? "Temporarily closed" : "Closed")}</div></div>
          <button class="btn ghost small" type="button" data-star="${esc(s.id)}">${S.fleet.includes(s.id) ? "★ In my fleet" : "☆ Add to my fleet"}</button></div>
        <div class="ucards">${classes.map((c) => unitCard(s.id, c)).join("")}</div>`;
      return;
    }
    const sort = $("m-sort").value;
    const rows = [...stores].sort((a, b) => sort === "id" ? a.id.localeCompare(b.id) : sort === "city" ? a.city.localeCompare(b.city) || a.id.localeCompare(b.id) : unitWorst(a.id) - unitWorst(b.id) || a.id.localeCompare(b.id));
    box.innerHTML = `<div class="card"><div class="tablewrap"><table class="mx"><thead><tr><th></th><th>Store</th>${classes.map((c) => `<th>${esc(SHORT[c.code])}</th>`).join("")}</tr></thead><tbody>` +
      rows.map((s) => `<tr><td class="star"><button type="button" data-star="${esc(s.id)}" title="${S.fleet.includes(s.id) ? "Remove from" : "Add to"} my fleet" aria-label="Toggle ${esc(s.id)} in my fleet">${S.fleet.includes(s.id) ? "★" : "☆"}</button></td>
        <td class="st"><button type="button" class="linkish" data-store="${esc(s.id)}" title="Monitor this store on its own"><b>${esc(s.id)}</b> ${esc(s.city)}</button>${s.open ? "" : ' <span class="pill off">Closed</span>'}</td>` +
        classes.map((c) => {
          const u = curIdx[unitKey(s.id, c.code)];
          const on = S.focus && S.focus.store === s.id && S.focus.cls === c.code;
          return `<td class="cellu${on ? " focus" : ""}" data-focus="${esc(s.id)}.${c.code}" tabindex="0">${statePill(c.code, u)} ${c.signal ? healthBadge(u) : u && u.grade != null ? gradeTag(u.grade) : ""} ${condBadge(u)}</td>`;
        }).join("") + `</tr>`).join("") + `</tbody></table></div></div>`;
  }
  const GR = {4: "A", 3: "B", 2: "C", 1: "D", 0: "F"};
  const gradeTag = (g) => `<span class="grade g${g}" style="width:22px;height:22px;font-size:12px;border-radius:6px;vertical-align:middle" title="Reliability grade">${GR[g]}</span>`;

  function unitCard(storeId, c) {
    const u = curIdx[unitKey(storeId, c.code)];
    const on = S.focus && S.focus.store === storeId && S.focus.cls === c.code;
    const since = u && u.since ? dur(Date.now() - Date.parse(u.since)) : "–";
    let body;
    if (c.signal) {
      body = `<div class="ubig">${u && u.value != null ? fmt1(u.value) : "–"}<small>${esc(c.unit || "")}</small></div>
        <div class="urow"><span>1-hour avg</span><b>${fmt1(u?.avg1h)} ${esc(c.unit || "")}</b></div>
        <div class="urow"><span>Baseline</span><b>${fmt1(u?.bMean)} ± ${fmt1(u?.bSd)}${u && u.bMode === 0 ? " (design)" : ""}</b></div>
        <div class="urow"><span>Health index</span><b>${healthBadge(u) || "–"}</b></div>`;
    } else {
      body = `<div class="ubig">${u && u.grade != null ? gradeTag(u.grade) : ""} ${fmt1(u?.score)}<small>reliability</small></div>
        <div class="urow"><span>Uptime 24h / 7d</span><b>${fmt1(u?.up24)}% / ${fmt1(u?.up7)}%</b></div>
        <div class="urow"><span>Failures 7d · MTTR</span><b>${fmt0(u?.failures7d)} · ${fmt1(u?.mttr)} h</b></div>
        <div class="urow"><span>Lost sales 7d</span><b>${usd(u?.lostUsd7d)}</b></div>`;
    }
    return `<button type="button" class="ucard${on ? " focus" : ""}" data-focus="${esc(storeId)}.${c.code}">
      <div class="utop"><span class="uname">${esc(c.name)}</span>${condBadge(u)}</div>
      <div>${statePill(c.code, u)} <span class="muted">for ${since}</span></div>${body}
      <div class="ugo">Open history →</div></button>`;
  }

  // ---------- canvas helpers ----------
  function setupCanvas(cv, cssH) {
    const w = cv.parentElement.clientWidth, dpr = window.devicePixelRatio || 1;
    cv.style.width = w + "px"; cv.style.height = cssH + "px";
    cv.width = Math.round(w * dpr); cv.height = Math.round(cssH * dpr);
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return {ctx, w, h: cssH};
  }
  let hatchCache = null;
  function hatch(ctx) {
    if (hatchCache) return hatchCache;
    const p = document.createElement("canvas"); p.width = 8; p.height = 8;
    const g = p.getContext("2d");
    g.fillStyle = CAT.fault.color; g.fillRect(0, 0, 8, 8);
    g.strokeStyle = "rgba(255,255,255,.55)"; g.lineWidth = 2;
    g.beginPath(); g.moveTo(-2, 10); g.lineTo(10, -2); g.moveTo(-2, 2); g.lineTo(2, -2); g.moveTo(6, 10); g.lineTo(10, 6); g.stroke();
    hatchCache = ctx.createPattern(p, "repeat");
    return hatchCache;
  }
  function fillFor(ctx, c) { return CAT[c].hatch ? hatch(ctx) : CAT[c].color; }

  function timeTicks(start, end, width) {
    const span = end - start, steps = [HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, 24 * HOUR];
    const step = steps.find((s) => span / s <= Math.max(3, width / 90)) || 24 * HOUR;
    const every = step / HOUR, key = `${start}|${end}|${every}`;
    if (tickCache.has(key)) return tickCache.get(key);
    // walk whole UTC hours and keep the ones whose Central (local) hour is a multiple of the step, so ticks stay on
    // local midnight / 6 AM etc. across a daylight-saving change
    const ticks = [];
    for (let t = Math.ceil(start / HOUR) * HOUR; t <= end; t += HOUR) {
      const h = +localHourF.format(new Date(t)) % 24;
      if (h % every !== 0) continue;
      ticks.push({t, label: step >= 24 * HOUR || h === 0 ? dayF.format(new Date(t)) : hourF.format(new Date(t)), major: h === 0});
    }
    if (tickCache.size > 50) tickCache.clear();
    tickCache.set(key, ticks);
    return ticks;
  }
  function drawTimeAxis(ctx, x0, x1, y, start, end) {
    const X = (t) => x0 + ((t - start) / (end - start)) * (x1 - x0);
    ctx.font = "600 11px 'Nunito Sans', sans-serif"; ctx.fillStyle = "#5B564B"; ctx.textAlign = "center"; ctx.textBaseline = "top";
    for (const tk of timeTicks(start, end, x1 - x0)) {
      const x = X(tk.t);
      if (x < x0 + 12 || x > x1 - 12) continue;
      ctx.fillStyle = tk.major ? "#27251F" : "#5B564B";
      ctx.font = `${tk.major ? 800 : 600} 11px 'Nunito Sans', sans-serif`;
      ctx.fillText(tk.label, x, y + 4);
    }
  }
  function gridLines(ctx, x0, x1, y0, y1, start, end) {
    const X = (t) => x0 + ((t - start) / (end - start)) * (x1 - x0);
    for (const tk of timeTicks(start, end, x1 - x0)) {
      const x = Math.round(X(tk.t)) + 0.5;
      ctx.strokeStyle = tk.major ? "rgba(39,37,31,.18)" : "rgba(39,37,31,.07)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, y0); ctx.lineTo(x, y1); ctx.stroke();
    }
  }

  // tooltip
  const tip = () => $("m-tip");
  function showTip(ev, rows) {
    const el = tip();
    el.replaceChildren();
    for (const r of rows) {
      const line = document.createElement("div");
      line.className = r.head ? "th" : "tr";
      if (r.color) { const k = document.createElement("i"); k.className = r.box ? "box" : "key"; k.style.background = r.color; line.appendChild(k); }
      if (r.value != null) { const b = document.createElement("b"); b.textContent = r.value; line.appendChild(b); }
      if (r.text) { const s = document.createElement("span"); s.textContent = r.text; line.appendChild(s); }
      el.appendChild(line);
    }
    el.style.display = "block";
    const pad = 14, bw = el.offsetWidth, bh = el.offsetHeight;
    let x = ev.clientX + pad, y = ev.clientY + pad;
    if (x + bw > window.innerWidth - 8) x = ev.clientX - bw - pad;
    if (y + bh > window.innerHeight - 8) y = ev.clientY - bh - pad;
    el.style.left = x + "px"; el.style.top = y + "px";
  }
  const hideTip = () => { tip().style.display = "none"; };

  // ---------- state timeline ----------
  // rows: [{label, cls, runs, store}], draws a strip per row, hover = state + run, click = focus
  function drawTimeline(cv, rows, start, end, {rowH, labels, onClick, left}) {
    const gutter = left ?? (labels ? 150 : 44), axis = 22;
    const h = rows.length * rowH + axis;
    const {ctx, w} = setupCanvas(cv, h);
    const x0 = gutter, x1 = w - 8;
    const X = (t) => x0 + ((Math.max(start, Math.min(end, t)) - start) / (end - start)) * (x1 - x0);
    ctx.clearRect(0, 0, w, h);
    rows.forEach((r, i) => {
      const y = i * rowH, hh = Math.max(2, rowH - (rowH >= 6 ? 2 : 1));
      if (labels) {
        ctx.font = "700 12px 'Nunito Sans', sans-serif"; ctx.fillStyle = "#27251F"; ctx.textAlign = "right"; ctx.textBaseline = "middle";
        ctx.fillText(r.label, gutter - 8, y + hh / 2, gutter - 14);
      }
      const runs = r.runs;
      if (!runs.length) { ctx.fillStyle = CAT.nodata.color; ctx.fillRect(x0, y, x1 - x0, hh); }
      if (runs.length && runs[0][0] > start) { ctx.fillStyle = CAT.nodata.color; ctx.fillRect(x0, y, X(runs[0][0]) - x0, hh); }
      for (let k = 0; k < runs.length; k++) {
        const a = X(runs[k][0]), b = X(k + 1 < runs.length ? runs[k + 1][0] : end);
        if (b <= a) continue;
        ctx.fillStyle = fillFor(ctx, category(r.cls, runs[k][1]));
        ctx.fillRect(a, y, Math.max(1, b - a), hh);
      }
      if (r.label && rowH >= 16 && r.inlineLabels) {
        ctx.font = "700 11px 'Nunito Sans', sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
        for (let k = 0; k < runs.length; k++) {
          const a = X(runs[k][0]), b = X(k + 1 < runs.length ? runs[k + 1][0] : end), lab = stateLabel(r.cls, runs[k][1]);
          ctx.font = "700 11px 'Nunito Sans', sans-serif";
          if (b - a > ctx.measureText(lab).width + 12) {
            const c = category(r.cls, runs[k][1]);
            ctx.fillStyle = c === "idle" || c === "nodata" ? "#27251F" : "#fff";
            ctx.fillText(lab, a + 6, y + hh / 2);
          }
        }
      }
    });
    gridLines(ctx, x0, x1, 0, rows.length * rowH, start, end);
    drawTimeAxis(ctx, x0, x1, rows.length * rowH, start, end);
    const hit = (ev) => {
      const rc = cv.getBoundingClientRect(), mx = ev.clientX - rc.left, my = ev.clientY - rc.top;
      const i = Math.floor(my / rowH);
      if (mx < x0 || mx > x1 || i < 0 || i >= rows.length) return null;
      const t = start + ((mx - x0) / (x1 - x0)) * (end - start), r = rows[i];
      let k = -1;
      for (let j = 0; j < r.runs.length; j++) if (r.runs[j][0] <= t) k = j; else break;
      return {r, t, k};
    };
    cv.onpointermove = (ev) => {
      const h0 = hit(ev);
      if (!h0) { hideTip(); cv.style.cursor = "default"; return; }
      cv.style.cursor = onClick ? "pointer" : "default";
      const {r, t, k} = h0;
      const code = k >= 0 ? r.runs[k][1] : null, c = category(r.cls, code);
      const t0 = k >= 0 ? r.runs[k][0] : start, t1 = k + 1 < r.runs.length ? r.runs[k + 1][0] : end;
      showTip(ev, [
        {head: true, text: `${r.tipName || r.label} · ${SHORT[r.cls]}`},
        {value: stateLabel(r.cls, code), color: CAT[c].color, box: true, text: CAT[c].label},
        {text: `${when(t0)} → ${k + 1 < r.runs.length ? when(t1) : "now"} (${dur(t1 - t0)})`},
        {text: `at ${when(t)}`},
      ]);
    };
    cv.onpointerleave = hideTip;
    cv.onclick = (ev) => { const h0 = hit(ev); if (h0 && onClick) onClick(h0.r); };
  }

  // ---------- line chart ----------
  // spec: {start, end, yMin, yMax, unit, zones:[{y0,y1,color,label}], bands:[{pts:[[t,lo,hi]],color}], lines:[{pts:[[t,v]],color,width,dash,label,step}]}
  function lineChart(cv, spec, height, group) {
    const draw = (hoverT) => {
      const {ctx, w, h} = setupCanvas(cv, height);
      const L = spec.left || 44, R = 12, T = 10, B = 24, x0 = L, x1 = w - R, y0 = T, y1 = h - B;
      const X = (t) => x0 + ((t - spec.start) / (spec.end - spec.start)) * (x1 - x0);
      const Y = (v) => y1 - ((v - spec.yMin) / (spec.yMax - spec.yMin)) * (y1 - y0);
      ctx.clearRect(0, 0, w, h);
      ctx.save(); ctx.beginPath(); ctx.rect(x0, y0, x1 - x0, y1 - y0); ctx.clip();
      for (const z of spec.zones || []) {
        ctx.fillStyle = z.color; ctx.fillRect(x0, Y(Math.min(z.y1, spec.yMax)), x1 - x0, Y(Math.max(z.y0, spec.yMin)) - Y(Math.min(z.y1, spec.yMax)));
      }
      ctx.restore();
      // y grid + labels
      const ticks = niceTicks(spec.yMin, spec.yMax, Math.max(3, Math.floor((y1 - y0) / 40)));
      ctx.font = "600 11px 'Nunito Sans', sans-serif"; ctx.textAlign = "right"; ctx.textBaseline = "middle";
      for (const v of ticks) {
        const y = Math.round(Y(v)) + 0.5;
        ctx.strokeStyle = "rgba(39,37,31,.08)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke();
        ctx.fillStyle = "#5B564B"; ctx.fillText(fmtTick(v), x0 - 6, y);
      }
      gridLines(ctx, x0, x1, y0, y1, spec.start, spec.end);
      ctx.save(); ctx.beginPath(); ctx.rect(x0, y0 - 2, x1 - x0, y1 - y0 + 4); ctx.clip();
      for (const z of spec.zones || []) if (z.label) {
        ctx.font = "700 10px 'Nunito Sans', sans-serif"; ctx.fillStyle = z.ink || "#5B564B"; ctx.textAlign = "left"; ctx.textBaseline = "top";
        ctx.fillText(z.label, x0 + 6, Y(Math.min(z.y1, spec.yMax)) + 3);
      }
      for (const b of spec.bands || []) {
        if (!b.pts.length) continue;
        ctx.fillStyle = b.color; ctx.beginPath();
        b.pts.forEach((p, i) => (i ? ctx.lineTo(X(p[0]), Y(p[2])) : ctx.moveTo(X(p[0]), Y(p[2]))));
        for (let i = b.pts.length - 1; i >= 0; i--) ctx.lineTo(X(b.pts[i][0]), Y(b.pts[i][1]));
        ctx.closePath(); ctx.fill();
      }
      for (const ln of spec.lines || []) {
        if (!ln.pts.length) continue;
        ctx.strokeStyle = ln.color; ctx.lineWidth = ln.width || 2; ctx.setLineDash(ln.dash || []); ctx.lineJoin = "round";
        ctx.beginPath();
        let prev = null;
        for (const p of ln.pts) {
          if (p[1] == null) { prev = null; continue; }
          const x = X(p[0]), y = Y(p[1]);
          if (prev == null) ctx.moveTo(x, y);
          else if (ln.step) { ctx.lineTo(x, prev); ctx.lineTo(x, y); }
          else ctx.lineTo(x, y);
          prev = y;
        }
        if (ln.step && prev != null) ctx.lineTo(x1, prev);
        ctx.stroke(); ctx.setLineDash([]);
      }
      ctx.restore();
      drawTimeAxis(ctx, x0, x1, y1, spec.start, spec.end);
      if (spec.unit) { ctx.font = "700 10px 'Nunito Sans', sans-serif"; ctx.fillStyle = "#5B564B"; ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.fillText(spec.unit, 2, 0); }
      if (hoverT != null && hoverT >= spec.start && hoverT <= spec.end) {
        const x = Math.round(X(hoverT)) + 0.5;
        ctx.strokeStyle = "rgba(39,37,31,.55)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, y0); ctx.lineTo(x, y1); ctx.stroke();
        for (const ln of spec.lines || []) {
          if (ln.noDot) continue;
          const v = valueAt(ln.pts, hoverT, ln.step);
          if (v == null) continue;
          ctx.fillStyle = ln.color; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.arc(x, Y(v), 4, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
        }
      }
      return {x0, x1};
    };
    const geo = draw(null);
    const chart = {cv, spec, draw, geo};
    const tFromEv = (ev) => { const rc = cv.getBoundingClientRect(), mx = ev.clientX - rc.left; if (mx < geo.x0 || mx > geo.x1) return null; return spec.start + ((mx - geo.x0) / (geo.x1 - geo.x0)) * (spec.end - spec.start); };
    cv.onpointermove = (ev) => {
      const t = tFromEv(ev);
      if (t == null) { hideTip(); (group || [chart]).forEach((c) => c.draw(null)); return; }
      (group || [chart]).forEach((c) => c.draw(t));
      const rows = [{head: true, text: when(t)}];
      for (const c of group || [chart]) for (const ln of c.spec.lines || []) {
        if (!ln.label) continue;
        const v = valueAt(ln.pts, t, ln.step);
        rows.push({color: ln.color, value: v == null ? "–" : fmt1(v) + (c.spec.unitShort ? " " + c.spec.unitShort : ""), text: ln.label});
      }
      if (spec.extraTip) rows.push(...spec.extraTip(t));
      showTip(ev, rows);
    };
    cv.onpointerleave = () => { hideTip(); (group || [chart]).forEach((c) => c.draw(null)); };
    if (group) group.push(chart);
    return chart;
  }
  function valueAt(pts, t, step) {
    if (!pts.length || t < pts[0][0]) return null;
    let lo = 0, hi = pts.length - 1;
    while (lo < hi) { const m = (lo + hi + 1) >> 1; if (pts[m][0] <= t) lo = m; else hi = m - 1; }
    if (step || lo === pts.length - 1) return pts[lo][1];
    const a = pts[lo], b = pts[lo + 1];
    if (a[1] == null || b[1] == null) return a[1];
    return Math.abs(t - a[0]) < Math.abs(b[0] - t) ? a[1] : b[1];
  }
  function niceTicks(a, b, n) {
    const span = b - a, raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag;
    const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag;
    const out = [];
    for (let v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) out.push(+v.toFixed(6));
    return out;
  }
  const fmtTick = (v) => (Math.abs(v) >= 100 || Number.isInteger(v) ? String(Math.round(v)) : v.toFixed(1));
  const HEALTH_ZONES = [
    {y0: 0, y1: 40, color: "rgba(200,38,26,.08)", label: "Danger < 40", ink: "#9E1E14"},
    {y0: 40, y1: 70, color: "rgba(227,154,0,.10)", label: "Warning < 70", ink: "#8A5A00"},
  ];

  // ---------- History ----------
  function renderHistory() {
    const box = $("m-hist-body");
    if (!catalog) return;
    const stores = scopeStores(), classes = scopeClasses();
    if (!stores.length || !classes.length) { box.innerHTML = ""; return; }
    if (!fleetData) { if (!box.children.length) box.innerHTML = `<div class="card empty">Loading history…</div>`; return; }
    const ids = new Set(stores.map((s) => s.id));
    const single = S.scope === "store";
    const {start, end, step} = fleetData;
    box.innerHTML = classes.map((c) => `<div class="card hcard"><div class="hhead"><h3>${esc(c.name)}</h3><span class="muted" id="hs-${c.code}"></span></div>
      ${c.signal || !single ? `<div class="msub">${c.signal ? (single ? "Health index" : "Health index: fleet average and worst unit") : "Machines serving (state Operational)"}</div><div class="cwrap"><canvas id="hc-${c.code}"></canvas></div>` : ""}
      <div class="msub">State timeline${single ? "" : ` · ${ids.size} stores, worst first · click a row to open it`}</div><div class="cwrap"><canvas id="tl-${c.code}"></canvas></div>
      <div class="legend" id="lg-${c.code}"></div></div>`).join("");
    for (const c of classes) {
      const units = fleetData.units.filter((u) => u.cls === c.code && ids.has(u.store));
      const faultMs = (u) => { let d = 0; for (let i = 0; i < u.states.length; i++) if (category(c.code, u.states[i][1]) === "fault") d += (i + 1 < u.states.length ? u.states[i + 1][0] : end) - u.states[i][0]; return d; };
      const minH = (u) => (u.health || []).reduce((m, v) => (v == null ? m : Math.min(m, v)), 101);
      units.forEach((u) => { u._fault = faultMs(u); u._minH = minH(u); });
      units.sort((a, b) => b._fault - a._fault || a._minH - b._minH || a.store.localeCompare(b.store));
      // trend
      const mid = (i) => start + (i + 0.5) * step;
      const rowH = single ? 26 : Math.max(4, Math.min(16, Math.floor(320 / Math.max(1, units.length))));
      const labels = single || rowH >= 11, left = labels ? (single ? 90 : 150) : 44;
      if (c.signal) {
        const avg = [], worst = [];
        for (let i = 0; i < 240; i++) {
          let s = 0, n = 0, w = null;
          for (const u of units) { const v = u.health && u.health[i]; if (v == null) continue; s += v; n++; w = w == null ? v : Math.min(w, v); }
          avg.push([mid(i), n ? s / n : null]); worst.push([mid(i), w]);
        }
        const lines = single ? [{pts: avg, color: SERIES[0], label: "Health index"}]
          : [{pts: worst, color: SERIES[1], label: "Worst unit", width: 2}, {pts: avg, color: SERIES[0], label: "Fleet average", width: 2}];
        lineChart($(`hc-${c.code}`), {start, end, yMin: 0, yMax: 100, zones: HEALTH_ZONES, lines, left}, 150);
      } else if (!single) {
        const share = [];
        for (let i = 0; i < 240; i++) {
          const t = mid(i); let on = 0, n = 0;
          for (const u of units) { const v = valueAt(u.states, t, true); if (u.states.length && t >= u.states[0][0]) { n++; if (v === 0) on++; } }
          share.push([t, n ? (100 * on) / n : null]);
        }
        lineChart($(`hc-${c.code}`), {start, end, yMin: 0, yMax: 100, unit: "%", unitShort: "%", lines: [{pts: share, color: SERIES[0], label: "Serving"}], left}, 130);
      }
      const rows = units.map((u) => ({label: single ? SHORT[c.code] : storeName(u.store), tipName: storeName(u.store), cls: c.code, runs: u.states, store: u.store, inlineLabels: single}));
      drawTimeline($(`tl-${c.code}`), rows, start, end, {rowH, labels, left, onClick: (r) => setFocus(r.store, c.code)});
      const totals = {};
      let tot = 0;
      for (const u of units) {
        const lead = (u.states.length ? u.states[0][0] : end) - start;   // before the first value we have = no data
        if (lead > 0) { totals.nodata = (totals.nodata || 0) + lead; tot += lead; }
        for (let i = 0; i < u.states.length; i++) {
          const d = (i + 1 < u.states.length ? u.states[i + 1][0] : end) - u.states[i][0], k = category(c.code, u.states[i][1]);
          totals[k] = (totals[k] || 0) + d; tot += d;
        }
      }
      $(`lg-${c.code}`).innerHTML = CAT_ORDER.filter((k) => totals[k]).map((k) => `<span><i class="sw ${k}"></i>${CAT[k].label} <b>${fmt1((100 * totals[k]) / tot)}%</b></span>`).join("") +
        (c.signal && !single ? `<span class="lkey"><i style="background:${SERIES[0]}"></i>Fleet average</span><span class="lkey"><i style="background:${SERIES[1]}"></i>Worst unit</span>` : "");
      const nf = units.filter((u) => u._fault > 0).length;
      $(`hs-${c.code}`).textContent = single ? "" : `${nf} of ${units.length} had a fault in the last ${rangeLabel()}`;
    }
  }

  // ---------- Focus ----------
  function focusStoresList() {
    const inScope = scopeStores();
    return inScope.length > 1 ? inScope : catalog.stores;
  }
  function renderFocusHead() {
    if (!catalog) return;
    const f = S.focus;
    $("m-focus").hidden = !f;
    if (!f) return;
    const sel = $("m-f-store");
    const list = focusStoresList();
    const opts = list.map((s) => `<option value="${esc(s.id)}">${esc(s.id)} · ${esc(s.city)}</option>`).join("");
    if (sel.dataset.sig !== String(list.length) + list[0]?.id) { sel.innerHTML = opts; sel.dataset.sig = String(list.length) + list[0]?.id; }
    if (!list.some((s) => s.id === f.store)) sel.insertAdjacentHTML("afterbegin", `<option value="${esc(f.store)}">${esc(storeName(f.store))}</option>`);
    sel.value = f.store;
    document.querySelectorAll("#m-f-cls button").forEach((b) => b.classList.toggle("on", b.dataset.cls === f.cls));
    const cmpSel = $("m-f-cmp");
    cmpSel.innerHTML = `<option value="">+ Compare with another store…</option>` + catalog.stores.filter((s) => s.id !== f.store && !S.cmp.includes(s.id)).map((s) => `<option value="${esc(s.id)}">${esc(s.id)} · ${esc(s.city)}</option>`).join("");
    cmpSel.disabled = S.cmp.length >= 2;
    $("m-f-cmpchips").innerHTML = S.cmp.map((id, i) => `<span class="mchip"><i class="lk" style="background:${SERIES[i + 1]}"></i>${esc(storeName(id))}<button type="button" data-cmprm="${esc(id)}" aria-label="Stop comparing ${esc(id)}">×</button></span>`).join("");
    const s = storeById[f.store], c = classByCode[f.cls], u = curIdx[unitKey(f.store, f.cls)];
    $("m-f-title").innerHTML = `${esc(c.name)} <span class="muted">at</span> ${esc(s.city)} <span class="muted">· ${esc(s.id)}</span>`;
    $("m-f-now").innerHTML = u ? `${statePill(f.cls, u)} <span class="muted">since ${u.since ? when(Date.parse(u.since)) : "–"}</span> ${c.signal ? `· now <b>${fmt1(u.value)} ${esc(c.unit || "")}</b> · health ${healthBadge(u)}` : `· reliability ${u.grade != null ? gradeTag(u.grade) : ""} <b>${fmt1(u.score)}</b>`} ${condBadge(u)}` : "";
  }

  function stepFn(pts) { return (t) => valueAt(pts, t, true); }

  function renderFocus() {
    if (!S.focus) return;
    const f = S.focus, c = classByCode[f.cls], d = unitData[unitKey(f.store, f.cls)];
    if (!d) return;
    const {start, end} = d;
    const group = [];
    const box = $("m-f-charts");
    box.innerHTML = (c.signal ? `<div class="msub">${esc(c.signal.replace(/([a-z])([A-Z])/g, "$1 $2"))} (${esc(c.unit || "")})</div><div class="cwrap"><canvas id="fc-sig"></canvas></div><div class="legend" id="fc-sig-lg"></div>` : "") +
      `<div class="msub">State</div><div class="cwrap"><canvas id="fc-state"></canvas></div>` +
      (S.cmp.length ? `<div class="cwrap"><canvas id="fc-state-cmp"></canvas></div>` : "") +
      (c.signal ? `<div class="msub">Health index</div><div class="cwrap"><canvas id="fc-health"></canvas></div>` : "");
    const others = S.cmp.map((st) => unitData[unitKey(st, f.cls)]).filter(Boolean);
    if (c.signal) {
      const mean = stepFn(d.bMean), sd = stepFn(d.bSd);
      const thr = (z) => d.signal.map((p) => { const m = mean(p[0]), s = sd(p[0]); return [p[0], m == null || s == null ? null : Math.min(m + z * s, c.normal + z * c.tol)]; });
      const warnL = thr(WARN_Z), dangerL = thr(DANGER_Z);
      const baseL = d.signal.map((p) => [p[0], mean(p[0])]);
      const vals = [];
      for (const p of d.signal) vals.push(p[1], p[3]);
      for (const o of others) for (const p of o.signal || []) vals.push(p[2]);
      for (const p of warnL) if (p[1] != null) vals.push(p[1]);
      vals.push(c.normal - c.tol, c.normal + c.tol);
      let lo = Math.min(...vals), hi = Math.max(...vals);
      const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
      // keep the danger line in view only when it's close
      const dMin = Math.min(...dangerL.filter((p) => p[1] != null).map((p) => p[1]));
      if (dMin < hi + (hi - lo) * 0.3) hi = Math.max(hi, dMin + pad);
      const lines = [
        {pts: d.signal.map((p) => [p[0], p[2]]), color: SERIES[0], width: 2, label: `${f.store} reading`},
        {pts: d.avg1h, color: "#27251F", width: 2, label: "1-hour steady-state average", step: false},
        {pts: baseL, color: "#8A8478", width: 1.5, dash: [5, 4], label: "Baseline", step: true, noDot: true},
        {pts: warnL, color: "#B87300", width: 1.5, dash: [2, 3], label: "Warning threshold (health 70)", step: true, noDot: true},
        {pts: dangerL, color: "#C8261A", width: 1.5, dash: [2, 3], label: "Danger threshold (health 40)", step: true, noDot: true},
      ];
      others.forEach((o, i) => lines.splice(1 + i, 0, {pts: (o.signal || []).map((p) => [p[0], p[2]]), color: SERIES[i + 1], width: 2, label: `${o.store} reading`}));
      lineChart($("fc-sig"), {start, end, yMin: lo, yMax: hi, unit: c.unit, unitShort: c.unit, left: 90,
        zones: [{y0: c.normal - c.tol, y1: c.normal + c.tol, color: "rgba(31,138,71,.09)", label: `Design normal ${fmt1(c.normal)} ± ${fmt1(c.tol)}`, ink: "#1F6B3A"}],
        bands: [{pts: d.signal.map((p) => [p[0], p[1], p[3]]), color: "rgba(42,120,214,.16)"}], lines}, 260, group);
      $("fc-sig-lg").innerHTML = [[SERIES[0], `${f.store} reading (shaded: min–max)`], ...others.map((o, i) => [SERIES[i + 1], `${o.store} reading`]), ["#27251F", "1-hour steady-state average"], ["#8A8478", "Baseline", true], ["#B87300", "Warning threshold", true], ["#C8261A", "Danger threshold", true]]
        .map(([col, lab, dash]) => `<span class="lkey${dash ? " dash" : ""}"><i style="background:${col}"></i>${esc(lab)}</span>`).join("");
      const hl = [{pts: d.health, color: SERIES[0], label: `${f.store} health`}];
      others.forEach((o, i) => hl.push({pts: o.health || [], color: SERIES[i + 1], label: `${o.store} health`}));
      lineChart($("fc-health"), {start, end, yMin: 0, yMax: 100, zones: HEALTH_ZONES, lines: hl, left: 90}, 150, group);
    }
    const stRows = [{label: f.store, tipName: storeName(f.store), cls: f.cls, runs: d.states, store: f.store, inlineLabels: true}];
    drawTimeline($("fc-state"), stRows, start, end, {rowH: 28, labels: true, left: 90});
    if (S.cmp.length) drawTimeline($("fc-state-cmp"), others.map((o) => ({label: o.store, tipName: storeName(o.store), cls: f.cls, runs: o.states, store: o.store, inlineLabels: true})), start, end, {rowH: 22, labels: true, left: 90, onClick: (r) => setFocus(r.store, f.cls, false)});
    // time in state
    const tis = {};
    const lead = (d.states.length ? d.states[0][0] : end) - start;
    if (lead > 0) tis["null"] = {code: null, ms: lead, n: 1};
    for (let i = 0; i < d.states.length; i++) {
      const code = d.states[i][1], dd = (i + 1 < d.states.length ? d.states[i + 1][0] : end) - d.states[i][0];
      const k = code == null ? "null" : code;
      tis[k] = tis[k] || {code, ms: 0, n: 0}; tis[k].ms += dd; tis[k].n += 1;
    }
    const total = end - start;
    $("m-f-tis").innerHTML = `<table class="tis"><thead><tr><th>State</th><th class="num">Time</th><th class="num">Share</th><th class="num">Times entered</th></tr></thead><tbody>` +
      Object.values(tis).sort((a, b) => b.ms - a.ms).map((x) => { const k = category(f.cls, x.code);
        return `<tr><td><i class="sw ${k}"></i>${esc(stateLabel(f.cls, x.code))} <span class="muted">${CAT[k].label}</span></td><td class="num">${dur(x.ms)}</td><td class="num">${fmt1((100 * x.ms) / total)}%</td><td class="num">${x.n}</td></tr>`; }).join("") + `</tbody></table>`;
    // events: fault / attention / no-data episodes
    const ev = [];
    for (let i = 0; i < d.states.length; i++) {
      const code = d.states[i][1], k = category(f.cls, code);
      if (!["fault", "alert", "nodata"].includes(k)) continue;
      const t1 = i + 1 < d.states.length ? d.states[i + 1][0] : null;
      ev.push({t0: d.states[i][0], t1, code, k});
    }
    ev.reverse();
    $("m-f-events").innerHTML = ev.length ? `<table class="tis"><thead><tr><th>Started</th><th>State</th><th class="num">Lasted</th></tr></thead><tbody>` +
      ev.slice(0, 40).map((e) => `<tr><td>${when(e.t0)}</td><td><i class="sw ${e.k}"></i>${esc(stateLabel(f.cls, e.code))}</td><td class="num">${e.t1 ? dur(e.t1 - e.t0) : `<b>ongoing</b> ${dur(end - e.t0)}`}</td></tr>`).join("") + `</tbody></table>`
      : `<div class="empty">No faults, alerts or data gaps in the last ${rangeLabel()}.</div>`;
  }

  // ---------- wiring ----------
  function wire() {
    $("m-scope").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.scope = b.dataset.scope; changed(); });
    $("m-store").addEventListener("change", (e) => { S.store = e.target.value; changed(); });
    $("m-terr").addEventListener("change", (e) => { S.terr = e.target.value; changed(); });
    $("m-eq").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      const c = b.dataset.cls;
      S.eq = S.eq.includes(c) ? S.eq.filter((x) => x !== c) : catalog.classes.map((x) => x.code).filter((x) => x === c || S.eq.includes(x));
      changed();
    });
    $("m-range").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.hours = +b.dataset.h; changed({units: true}); });
    $("m-sort").addEventListener("change", renderNow);
    $("m-fleet-add").addEventListener("change", (e) => {
      const v = e.target.value.trim().toLowerCase();
      const hit = catalog.stores.filter((s) => s.id.toLowerCase() === v || `${s.id} · ${s.city}`.toLowerCase() === v);
      const list = hit.length ? hit : catalog.stores.filter((s) => s.city.toLowerCase() === v);
      if (list.length) { S.fleet = [...new Set([...S.fleet, ...list.map((s) => s.id)])].sort(); saveFleet(); e.target.value = ""; changed({fleet: true}); }
    });
    $("m-fleet-terr").addEventListener("change", (e) => {
      if (!e.target.value) return;
      S.fleet = [...new Set([...S.fleet, ...catalog.stores.filter((s) => s.territory === e.target.value).map((s) => s.id)])].sort();
      saveFleet(); e.target.value = ""; changed();
    });
    $("m-fleet-clear").addEventListener("click", () => { S.fleet = []; saveFleet(); changed(); });
    $("m-fleet-chips").addEventListener("click", (e) => { const b = e.target.closest("[data-rm]"); if (b) toggleFleet(b.dataset.rm); });
    $("m-now").addEventListener("click", (e) => {
      const star = e.target.closest("[data-star]"); if (star) { toggleFleet(star.dataset.star); return; }
      const st = e.target.closest("[data-store]"); if (st) { S.scope = "store"; S.store = st.dataset.store; changed(); return; }
      const fc = e.target.closest("[data-focus]"); if (fc) { const [s, c] = fc.dataset.focus.split("."); setFocus(s, c); }
    });
    $("m-now").addEventListener("keydown", (e) => { if (e.key !== "Enter") return; const fc = e.target.closest("[data-focus]"); if (fc) { const [s, c] = fc.dataset.focus.split("."); setFocus(s, c); } });
    $("m-f-store").addEventListener("change", (e) => setFocus(e.target.value, S.focus.cls, false));
    $("m-f-cls").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setFocus(S.focus.store, b.dataset.cls, false); });
    const stepStore = (dir) => { const list = focusStoresList(), i = list.findIndex((s) => s.id === S.focus.store); setFocus(list[(i + dir + list.length) % list.length].id, S.focus.cls, false); };
    $("m-f-prev").addEventListener("click", () => stepStore(-1));
    $("m-f-next").addEventListener("click", () => stepStore(1));
    $("m-f-cmp").addEventListener("change", (e) => { if (e.target.value) { S.cmp = [...S.cmp, e.target.value].slice(0, 2); writeHash(); renderFocusHead(); loadUnits(); } });
    $("m-f-cmpchips").addEventListener("click", (e) => { const b = e.target.closest("[data-cmprm]"); if (b) { S.cmp = S.cmp.filter((x) => x !== b.dataset.cmprm); writeHash(); renderFocusHead(); loadUnits(); } });
    $("m-f-single").addEventListener("click", () => { S.scope = "store"; S.store = S.focus.store; changed(); });
    let rz = null;
    window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { if (active()) { renderHistory(); renderFocus(); } }, 150); });
  }

  const active = () => !$("monitor").hidden;
  let started = false, timers = [];
  let starting = null;
  function start() {   // one run at a time (a hash change can call this while the catalog is still loading)
    if (!starting) starting = run().finally(() => { starting = null; });
    return starting;
  }
  async function run() {
    if (!catalog) {
      try { catalog = await getJSON("/api/monitor/catalog"); }
      catch (e) { showErr(`Couldn't load the store list: ${e.message}`); return; }
      for (const s of catalog.stores) storeById[s.id] = s;
      for (const c of catalog.classes) classByCode[c.code] = c;
      if (!storeById[S.store]) S.store = catalog.stores[0].id;
      if (!S.terr) S.terr = catalog.territories[0];
      $("m-store").innerHTML = catalog.stores.map((s) => `<option value="${esc(s.id)}">${esc(s.id)} · ${esc(s.city)} · ${esc(s.address)}</option>`).join("");
      $("m-terr").innerHTML = catalog.territories.map((t) => `<option>${esc(t)}</option>`).join("");
      $("m-fleet-terr").innerHTML = `<option value="">+ Add a territory…</option>` + catalog.territories.map((t) => `<option>${esc(t)}</option>`).join("");
      $("m-fleet-list").innerHTML = catalog.stores.map((s) => `<option value="${esc(s.id)} · ${esc(s.city)}"></option>`).join("");
      $("m-eq").innerHTML = catalog.classes.map((c) => `<button type="button" class="chip" data-cls="${c.code}">${esc(SHORT[c.code])}</button>`).join("");
      $("m-f-cls").innerHTML = catalog.classes.map((c) => `<button type="button" data-cls="${c.code}">${esc(SHORT[c.code])}</button>`).join("");
      if (S.focus && (!storeById[S.focus.store] || !classByCode[S.focus.cls])) S.focus = null;
      if (!S.focus) S.focus = {store: S.scope === "store" ? S.store : (scopeStores()[0] || catalog.stores[0]).id, cls: S.eq[0] || "COOLER"};
      wire();
    }
    writeHash(); renderControls(); renderNow(); renderFocusHead();
    await loadCurrent();
    loadFleet(); loadUnits();
    if (!started) {
      started = true;
      timers.push(setInterval(() => { if (active()) loadCurrent(); }, 30000));
      timers.push(setInterval(() => { if (active()) { loadFleet(); loadUnits(); } }, 60000));
    } else { renderHistory(); renderFocus(); }
  }

  window.Monitor = {start, readHash};
})();
