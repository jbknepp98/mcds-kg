// Fleet Tracker tab: every technician's van on a statewide map with every store.
// Vans, drivers and live GPS come from Atlas (ServiceTruck.GpsLatitude/GpsLongitude/TruckStatus, fed by Connect from
// the Postgres route plan); a selected van's road trail comes from Atlas history (UNWIND) via /api/truck/track.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const STATUS = {0: "Off duty", 10: "Driving", 20: "On site", 30: "Lunch"};
  const COND = {0: "Healthy", 1: "Warning", 2: "Danger", 3: "Fault"};
  const COND_COLOR = {0: "#1F8A47", 1: "#E39A00", 2: "#DD6B20", 3: "#C8261A"};
  const CERT_FOR = {COOLER: "REFRIG", FREEZER: "REFRIG", HVAC: "HVAC", GENERATOR: "GEN", SOFTSERVE: "TAYLOR"};
  const LEVEL = {SENIOR: "Senior", TECHNICIAN: "Technician", APPRENTICE: "Apprentice"};
  const ORDER = {10: 0, 20: 1, 30: 2, 0: 3};
  const NEAR_MI = 30;
  const VAN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 7a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v1h2.6a2 2 0 0 1 1.7.9l1.4 2.2c.2.3.3.7.3 1.1V16a1 1 0 0 1-1 1h-1.1a2.5 2.5 0 0 1-4.8 0H8.9a2.5 2.5 0 0 1-4.8 0H3a1 1 0 0 1-1-1V7zm14 3v3h4.2l-1.6-2.6a1 1 0 0 0-.8-.4H16z"/></svg>';

  const S = {terr: "", status: "", q: "", van: null, names: !window.matchMedia("(max-width: 600px)").matches, stores: "all"};
  let data = null, map = null, storeLayer, vanLayer, trailLayer, planLayer, timer = null, wired = false, starting = null, loadSeq = 0, trailSeq = 0;
  const vanMarkers = {}, storeMarkers = {};
  let storeById = {};

  // ---------- helpers ----------
  const nowHM = () => new Intl.DateTimeFormat("en-GB", {hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/Chicago"}).format(new Date());
  function hm12(hm) {
    if (!hm) return "";
    const [h, m] = hm.split(":").map(Number);
    return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
  }
  const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString("en-US", {hour: "numeric", minute: "2-digit", timeZone: "America/Chicago"}) : "");
  const city = (id) => (storeById[id] ? storeById[id].city : id);
  const first = (n) => String(n || "").split(" ")[0];
  function miles(a, b) {
    const R = 3958.8, r = Math.PI / 180;
    const dl = (b.lat - a.lat) * r, dn = (b.lon - a.lon) * r;
    const h = Math.sin(dl / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dn / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  const hasCert = (v, cls) => v.certs.some((c) => c.code === CERT_FOR[cls]);
  const statusKey = (v) => (v.status == null ? 0 : v.status);

  function stopUntil(v) {   // the planned departure from the stop the van is at now
    const n = nowHM();
    const s = v.plan.find((p) => (p.kind === "SERVICE" || p.kind === "LUNCH") && p.arrive <= n && n < p.depart && p.store === v.at);
    return s ? s.depart : null;
  }
  function nowLine(v) {
    const st = statusKey(v);
    if (st === 10) return `Driving to ${city(v.next)}${v.eta ? ` · ETA ${clock(v.eta)}` : ""}`;
    if (st === 20) { const u = stopUntil(v); return `On site in ${city(v.at)}${u ? ` until ${hm12(u)}` : ""}`; }
    if (st === 30) { const u = stopUntil(v); return `Lunch in ${city(v.at)}${u ? ` until ${hm12(u)}` : ""}`; }
    const n = nowHM(), start = v.plan.find((p) => p.kind === "START"), end = v.plan.find((p) => p.kind === "END");
    if (!v.plan.length) return `Off duty · no route today · parked in ${city(v.at || v.home)}`;
    if (start && n < start.depart) return `Off duty · leaves ${city(v.home)} at ${hm12(start.depart)}`;
    if (end && n >= end.arrive) return `Off duty · back in ${city(v.home)} since ${hm12(end.arrive)}`;
    return `Off duty · parked in ${city(v.at || v.home)}`;
  }
  function progress(v) {
    const svc = v.plan.filter((p) => p.kind === "SERVICE");
    if (!svc.length) return "";
    const n = nowHM();
    const done = svc.filter((p) => p.depart <= n).length;
    return `${done} of ${svc.length} jobs done`;
  }

  // ---------- URL ----------
  function readHash() {
    const q = new URLSearchParams((location.hash.split("?")[1]) || "");
    S.terr = q.get("terr") || "";
    S.status = q.get("status") || "";
    S.van = q.get("van") || null;
  }
  function writeHash() {
    const q = new URLSearchParams();
    if (S.terr) q.set("terr", S.terr);
    if (S.status) q.set("status", S.status);
    if (S.van) q.set("van", S.van);
    const h = "#fleet" + (q.toString() ? "?" + q.toString() : "");
    if (location.hash !== h) history.replaceState(null, "", h);
  }

  // ---------- map ----------
  function initMap() {
    map = L.map("fmap", {scrollWheelZoom: true, zoomSnap: 0.5}).setView([34.8, -92.4], 7);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', maxZoom: 18,
    }).addTo(map);
    storeLayer = L.layerGroup().addTo(map);
    trailLayer = L.layerGroup().addTo(map);
    planLayer = L.layerGroup().addTo(map);
    vanLayer = L.layerGroup().addTo(map);
    const ctl = L.control({position: "topright"});
    ctl.onAdd = () => {
      const d = L.DomUtil.create("div", "trucks-ctl");
      d.innerHTML = `<label><input type="checkbox" id="ft-names"${S.names ? " checked" : ""}> Driver names</label>
        <label style="margin-top:4px">Stores <select id="ft-stores" style="font:700 12px 'Nunito Sans';margin-left:4px">
          <option value="all">All 191</option><option value="issues">With a problem</option><option value="faults">Faults only</option><option value="none">Hide</option></select></label>`;
      L.DomEvent.disableClickPropagation(d);
      L.DomEvent.disableScrollPropagation(d);
      d.querySelector("#ft-names").addEventListener("change", (e) => { S.names = e.target.checked; drawVans(false); });
      d.querySelector("#ft-stores").addEventListener("change", (e) => { S.stores = e.target.value; drawStores(); });
      return d;
    };
    ctl.addTo(map);
    map.on("click", () => { if (S.van) select(null); });
  }

  function storePopup(s) {
    const cls = data.classes;
    const iss = s.issues.length
      ? `<div style="margin-top:4px">${s.issues.map((i) => `<div><span class="sdot c${i.cond}"></span> ${esc(cls[i.cls] || i.cls)}: <b style="font-family:inherit;font-weight:800">${COND[i.cond]}</b>${i.health != null && i.cond < 3 ? ` · health ${Math.round(i.health)}` : ""}</div>`).join("")}</div>`
      : `<div style="color:#1F8A47;font-weight:800;margin-top:4px">All 5 units healthy</div>`;
    const worst = s.issues[0];
    let near = "";
    const vans = data.vans.filter((v) => v.lat != null).map((v) => ({v, d: miles(v, s)})).sort((a, b) => a.d - b.d).slice(0, 3);
    if (vans.length) {
      near = `<div style="margin-top:8px;font-weight:800">Nearest vans right now</div>` + vans.map(({v, d}) => {
        const ok = worst ? hasCert(v, worst.cls) : null;
        const tag = ok == null ? "" : ok ? ` · <span style="color:#1F8A47;font-weight:800">certified</span>` : ` · <span style="color:#C8261A;font-weight:800">not certified</span>`;
        return `<div><a href="#" onclick="fleetSelect('${esc(v.truck)}');return false">${esc(v.name)}</a> · ${d.toFixed(0)} mi · ${esc(STATUS[statusKey(v)])}${tag}</div>`;
      }).join("") + (worst ? `<div style="color:#5B564B;font-size:12px">Certification for ${esc(cls[worst.cls] || worst.cls)} · straight-line miles</div>` : "");
    }
    return `<b>${esc(s.city)}</b> · ${esc(s.id)}<br><span style="color:#5B564B">${esc(s.address)} · ${esc(s.territory)}</span>${iss}${near}
      <div style="margin-top:6px"><a href="#monitor?scope=store&store=${encodeURIComponent(s.id)}">Monitor this store →</a></div>`;
  }

  function drawStores() {
    storeLayer.clearLayers();
    for (const k in storeMarkers) delete storeMarkers[k];
    if (S.stores === "none") return;
    const R = {0: 4, 1: 6, 2: 6.5, 3: 7.5};
    const sorted = [...data.stores].sort((a, b) => a.cond - b.cond);   // faults on top
    for (const s of sorted) {
      if (S.stores === "issues" && !s.cond) continue;
      if (S.stores === "faults" && s.cond < 3) continue;
      const dim = S.terr && s.territory !== S.terr;
      const m = L.circleMarker([s.lat, s.lon], {radius: R[s.cond], color: "#fff", weight: 1.5, fillColor: COND_COLOR[s.cond],
        fillOpacity: dim ? 0.18 : s.cond ? 1 : 0.6, opacity: dim ? 0.3 : 1});
      m.bindPopup(() => storePopup(s), {maxWidth: 300});
      m.bindTooltip(`${s.city} · ${COND[s.cond]}`, {direction: "top", offset: [0, -4]});
      m.addTo(storeLayer);
      storeMarkers[s.id] = m;
    }
  }

  function vanIcon(v) {
    const sel = S.van === v.truck ? " sel" : "";
    return L.divIcon({className: "", iconSize: null, iconAnchor: [0, 0],
      html: `<div class="vpin s${statusKey(v)}${sel}${S.names ? "" : " nolabel"}">${VAN}<span>${esc(first(v.name))}</span></div>`});
  }
  function animate(m, to) {
    const from = m.getLatLng();
    if (from.lat === to[0] && from.lng === to[1]) return;
    if (miles({lat: from.lat, lon: from.lng}, {lat: to[0], lon: to[1]}) > 40) { m.setLatLng(to); return; }
    const t0 = performance.now(), D = 1500;
    const step = (t) => {
      const f = Math.min(1, (t - t0) / D), e = f < 0.5 ? 2 * f * f : 1 - (-2 * f + 2) ** 2 / 2;
      m.setLatLng([from.lat + (to[0] - from.lat) * e, from.lng + (to[1] - from.lng) * e]);
      if (f < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  function drawVans(move) {
    const seen = new Set();
    for (const v of data.vans) {
      if (v.lat == null) continue;
      seen.add(v.truck);
      const dim = S.terr && v.territory !== S.terr;
      let m = vanMarkers[v.truck];
      if (!m) {
        m = L.marker([v.lat, v.lon], {icon: vanIcon(v), keyboard: true, title: `${v.name}, ${STATUS[statusKey(v)]}`});
        m.on("click", (e) => { L.DomEvent.stopPropagation(e); select(v.truck); });
        m.addTo(vanLayer);
        vanMarkers[v.truck] = m;
      } else {
        m.setIcon(vanIcon(v));
        if (move) animate(m, [v.lat, v.lon]); else m.setLatLng([v.lat, v.lon]);
      }
      m.setOpacity(dim ? 0.35 : 1);
      m.setZIndexOffset(S.van === v.truck ? 3000 : statusKey(v) === 10 ? 1000 : 500);
    }
    for (const k of Object.keys(vanMarkers)) if (!seen.has(k)) { vanLayer.removeLayer(vanMarkers[k]); delete vanMarkers[k]; }
  }

  async function drawTrail(v, fit) {
    const my = ++trailSeq;
    trailLayer.clearLayers();
    planLayer.clearLayers();
    if (!v) return;
    const n = nowHM();
    const pts = [];
    // planned stops still to come: numbered; stops already done: small dark dots
    let k = 0;
    for (const p of v.plan) {
      if (p.kind !== "SERVICE") continue;
      k++;
      const s = storeById[p.store];
      if (!s) continue;
      pts.push([s.lat, s.lon]);
      const done = p.depart <= n;
      L.marker([s.lat, s.lon], {zIndexOffset: 1500, icon: L.divIcon({className: "", iconSize: null, iconAnchor: [9, 9],
        html: `<span class="fsnum" style="${done ? "background:#5B564B;border-color:#5B564B;color:#fff" : ""}">${k}</span>`})})
        .bindTooltip(`${k}. ${s.city} · ${hm12(p.arrive)}–${hm12(p.depart)}${done ? " (done)" : ""}`).addTo(planLayer);
    }
    try {
      const r = await fetch(`/api/truck/track?truck=${encodeURIComponent(v.truck)}`);
      const j = await r.json();
      if (my !== trailSeq || !r.ok) return;
      const line = j.points.map((p) => [p[1], p[2]]);
      if (line.length > 1) {
        L.polyline(line, {color: "#fff", weight: 7, opacity: 0.9, interactive: false}).addTo(trailLayer);
        L.polyline(line, {color: "#2a78d6", weight: 4, interactive: false}).addTo(trailLayer);
        pts.push(...line);
      }
    } catch (e) { /* the plan markers still show */ }
    if (fit && my === trailSeq) {
      pts.push([v.lat, v.lon]);
      map.fitBounds(L.latLngBounds(pts).pad(0.2), {maxZoom: 12});
    }
  }

  // ---------- side panel ----------
  function filtered() {
    const q = S.q.trim().toLowerCase();
    return data.vans.filter((v) => {
      if (S.terr && v.territory !== S.terr) return false;
      const st = statusKey(v);
      if (S.status === "20" && !(st === 20 || st === 30)) return false;
      if (S.status && S.status !== "20" && String(st) !== S.status) return false;
      if (q && ![v.name, v.truck, v.territory, city(v.at), city(v.next), city(v.home), v.plate].some((x) => String(x || "").toLowerCase().includes(q))) return false;
      return true;
    }).sort((a, b) => ORDER[statusKey(a)] - ORDER[statusKey(b)] || a.name.localeCompare(b.name));
  }
  function renderList() {
    const rows = filtered();
    $("ft-list").innerHTML = rows.length ? rows.map((v) => `
      <button type="button" class="vrow${S.van === v.truck ? " sel" : ""}" data-van="${esc(v.truck)}">
        <i class="vdot s${statusKey(v)}"></i>
        <span class="who">${esc(v.name)} <small>· ${esc(LEVEL[v.level] || v.level)}</small></span>
        <span class="trk">${esc(v.truck)}</span>
        <span class="what">${esc(nowLine(v))}</span>
        <span class="meta">${esc(v.territory || "")}${progress(v) ? " · " + esc(progress(v)) : ""}</span>
      </button>`).join("") : `<div class="empty" style="padding:12px">No vans match.</div>`;
  }
  function renderDetail() {
    const box = $("ft-detail");
    const v = S.van && data.vans.find((x) => x.truck === S.van);
    if (!v) { box.hidden = true; box.innerHTML = ""; return; }
    box.hidden = false;
    const n = nowHM();
    const svcIdx = {};
    let k = 0;
    v.plan.forEach((p) => { if (p.kind === "SERVICE") svcIdx[p.seq] = ++k; });
    const stops = v.plan.map((p) => {
      const t = p.kind === "START" ? p.depart : p.arrive;
      let cls = "";
      if (p.kind === "START") cls = p.depart <= n ? "done" : "";
      else if (p.kind === "END") cls = p.arrive <= n ? "done" : (statusKey(v) === 10 && v.next === p.store && !v.plan.some((x) => x.kind === "SERVICE" && x.arrive > n)) ? "cur" : "";
      else if (p.depart <= n) cls = "done";
      else if (p.arrive <= n) cls = "cur";
      else if (statusKey(v) === 10 && p.store === v.next && !v.plan.some((x) => x.kind !== "START" && x.arrive > n && x.arrive < p.arrive)) cls = "cur";
      const where = `<a href="#" onclick="fleetStore('${esc(p.store)}');return false">${esc(city(p.store))}</a>`;
      const label = p.kind === "START" ? `Leaves home base, ${where}` : p.kind === "END" ? `Back at home base, ${where}`
        : p.kind === "LUNCH" ? `Lunch in ${where} <span class="k">until ${hm12(p.depart)}</span>`
        : `${svcIdx[p.seq]}. ${where} <span class="k">${esc(p.store)} · until ${hm12(p.depart)}</span>`;
      return `<li class="${cls}"><span class="t">${esc(hm12(t).replace(" AM", "a").replace(" PM", "p"))}</span><i class="m"></i><span>${label}</span></li>`;
    }).join("");
    const yrs = v.hired ? Math.max(0, new Date().getFullYear() - Number(v.hired.slice(0, 4))) : null;
    box.innerHTML = `
      <button type="button" class="back" id="ft-back">← All vans</button>
      <h3>${esc(v.name)}</h3>
      <div class="sub2">${esc(LEVEL[v.level] || v.level)}${yrs != null ? ` · ${yrs ? yrs + " yr" + (yrs === 1 ? "" : "s") : "new this year"}` : ""} · ${esc(v.territory || "")} · home base ${esc(city(v.home))}</div>
      <div class="now"><i class="vdot s${statusKey(v)}"></i>${esc(nowLine(v))}</div>
      <div class="sub2">${esc(v.truck)} · ${esc(v.year)} ${esc(v.make)} ${esc(v.model)} · plate ${esc(v.plate)}</div>
      <div class="certs">${v.certs.map((c) => `<span title="${esc(c.name)}">${esc(c.code)}</span>`).join("") || '<span>No current certifications</span>'}</div>
      <div style="font-weight:800;margin-top:4px">Today's route ${progress(v) ? `<span class="sub2">· ${esc(progress(v))}</span>` : ""}</div>
      ${v.plan.length ? `<ul class="stops">${stops}</ul>` : `<div class="sub2">No route today. The van stays parked at home base.</div>`}
      <div class="sub2">GPS ${esc(clock(v.fix)) || "–"} · live from Atlas · route on real roads</div>`;
    $("ft-back").addEventListener("click", () => select(null));
  }
  function renderKpis() {
    const vs = data.vans, c = (f) => vs.filter(f).length;
    const drive = c((v) => statusKey(v) === 10), site = c((v) => statusKey(v) === 20), lunch = c((v) => statusKey(v) === 30), off = c((v) => statusKey(v) === 0);
    const faults = data.stores.filter((s) => s.cond === 3);
    const covered = faults.filter((s) => s.issues.filter((i) => i.cond === 3).some((i) =>
      vs.some((v) => v.lat != null && statusKey(v) !== 0 && hasCert(v, i.cls) && miles(v, s) <= NEAR_MI))).length;
    const tile = (cls, color, label, value, note) => `<div class="kpi" style="border-top-color:${color}"><div class="label">${label}</div><div class="value">${value}</div><div class="note">${note}</div></div>`;
    $("ft-kpis").innerHTML =
      tile("", "var(--v-drive)", "Driving", drive, "on the road now") +
      tile("", "var(--v-site)", "On site", site + lunch, lunch ? `${lunch} on lunch` : "working a job") +
      tile("", "var(--v-off)", "Off duty", off, `of ${vs.length} vans`) +
      tile("", "var(--c3)", "Stores in fault", faults.length, `of ${data.stores.length} restaurants`) +
      tile("", "var(--ok)", "Faults with help nearby", faults.length ? `${covered}/${faults.length}` : "–",
        `an on-duty van certified for the fault within ${NEAR_MI} mi`);
  }

  // ---------- certification matrix ----------
  const CLS_NAME = {COOLER: "Cooler", FREEZER: "Freezer", HVAC: "HVAC", GENERATOR: "Generator", SOFTSERVE: "Soft serve"};
  const LEVEL_ORDER = {SENIOR: 0, TECHNICIAN: 1, APPRENTICE: 2};
  const WARN_DAYS = 90;
  const fmtDate = (d, withYear) => new Date(d + "T12:00:00").toLocaleDateString("en-US", withYear ? {month: "short", day: "numeric", year: "numeric"} : {month: "short", year: "numeric"});
  function certState(v, code) {
    const h = v.held.find((x) => x.code === code);
    if (!h) return {k: "none"};
    const days = h.expires ? Math.round((new Date(h.expires + "T12:00:00") - new Date(data.today + "T12:00:00")) / 86400000) : null;
    if (!h.current || (days != null && days < 0)) return {k: "bad", h, days};
    if (days != null && days <= WARN_DAYS) return {k: "warn", h, days};
    return {k: "ok", h, days};
  }
  function renderCerts() {
    const cat = data.certCatalog;
    const vans = data.vans.filter((v) => !S.terr || v.territory === S.terr);
    const terrs = [...new Set(vans.map((v) => v.territory))].sort();
    const isCur = (st) => st.k === "ok" || st.k === "warn";
    const head = `<thead><tr><th class="l">Technician</th><th class="l vancol">Van</th>${cat.map((c) => `<th data-cert="${esc(c.code)}">${esc(c.code)}<span class="cn">${esc(c.name)}</span><span class="cf">${c.classes.length ? "for " + c.classes.map((k) => CLS_NAME[k] || k).join(", ") : ""}</span></th>`).join("")}<th>Current</th></tr></thead>`;
    let body = "";
    for (const t of terrs) {
      const tv = vans.filter((v) => v.territory === t).sort((a, b) => (LEVEL_ORDER[a.level] ?? 9) - (LEVEL_ORDER[b.level] ?? 9) || a.name.localeCompare(b.name));
      body += `<tr class="terr"><td class="l">${esc(t)} <span class="sub2">· ${tv.length} technicians</span></td><td class="vancol"></td>${cat.map((c) => {
        const n = tv.filter((v) => isCur(certState(v, c.code))).length;
        return `<td><span class="cc ${n ? "cnt" : "gap"}" data-tip="terr" data-terr="${esc(t)}" data-cert="${esc(c.code)}">${n}</span></td>`;
      }).join("")}<td></td></tr>`;
      for (const v of tv) {
        const cells = cat.map((c) => {
          const st = certState(v, c.code);
          const tip = `data-tip="cell" data-van="${esc(v.truck)}" data-cert="${esc(c.code)}"`;
          if (st.k === "none") return `<td><span class="cell" ${tip}><b class="cc none" aria-label="Not held">–</b></span></td>`;
          if (st.k === "bad") return `<td><span class="cell" ${tip}><b class="cc bad">✕</b><small>expired ${st.h.expires ? esc(fmtDate(st.h.expires)) : ""}</small></span></td>`;
          if (st.k === "warn") return `<td><span class="cell" ${tip}><b class="cc warn">!</b><small>${st.days === 0 ? "expires today" : `${st.days} day${st.days === 1 ? "" : "s"} left`}</small></span></td>`;
          return `<td><span class="cell" ${tip}><b class="cc ok">✓</b><small>${st.h.expires ? "to " + esc(fmtDate(st.h.expires)) : "lifetime"}</small></span></td>`;
        }).join("");
        const cur = cat.filter((c) => isCur(certState(v, c.code))).length;
        body += `<tr class="tech${S.van === v.truck ? " sel" : ""}" data-van="${esc(v.truck)}" tabindex="0">
          <td class="l"><span class="who">${esc(v.name)} <small>· ${esc(LEVEL[v.level] || v.level)}</small></span><span class="van mob"><br>${esc(v.truck)}</span></td>
          <td class="l vancol"><span class="van"><i class="vdot s${statusKey(v)}" style="width:9px;height:9px;vertical-align:0"></i> ${esc(v.truck)}</span></td>
          ${cells}<td><b>${cur}</b><span class="sub2"> of ${cat.length}</span></td></tr>`;
      }
    }
    const foot = `<tfoot><tr><td class="l">${S.terr ? esc(S.terr) : "Statewide"}: current holders</td><td class="vancol"></td>${cat.map((c) => {
      const n = vans.filter((v) => isCur(certState(v, c.code))).length;
      return `<td>${n} <span class="sub2">of ${vans.length}</span></td>`;
    }).join("")}<td></td></tr></tfoot>`;
    $("ft-cmx").innerHTML = head + `<tbody>${body}</tbody>` + foot;

    // summary chips: what needs attention
    const expiring = [], expired = [], gaps = [];
    for (const v of vans) for (const c of cat) {
      const st = certState(v, c.code);
      if (st.k === "warn") expiring.push(`${first(v.name)} ${c.code} (${st.days}d)`);
      if (st.k === "bad") expired.push(`${first(v.name)} ${c.code}`);
    }
    for (const t of terrs) for (const c of cat) {
      if (!vans.filter((v) => v.territory === t).some((v) => isCur(certState(v, c.code)))) gaps.push(`${t.replace(" Arkansas", "")}: ${c.code}`);
    }
    const chip = (cls, sym, text) => `<span class="chip2"><b class="cc ${cls}">${sym}</b>${text}</span>`;
    $("ft-certsum").innerHTML =
      chip("bad", "✕", `${expired.length} expired${expired.length ? ": " + esc(expired.join(", ")) : ""}`) +
      chip("warn", "!", `${expiring.length} expiring within ${WARN_DAYS} days${expiring.length ? ": " + esc(expiring.join(", ")) : ""}`) +
      chip("gap", "0", `${gaps.length} territory gap${gaps.length === 1 ? "" : "s"}${gaps.length ? ": " + esc(gaps.join(", ")) : ""}`);
  }
  function certTip(el) {
    const cat = Object.fromEntries(data.certCatalog.map((c) => [c.code, c]));
    const c = cat[el.dataset.cert];
    if (el.dataset.tip === "terr") {
      const names = data.vans.filter((v) => v.territory === el.dataset.terr && ["ok", "warn"].includes(certState(v, c.code).k)).map((v) => v.name);
      return `<b>${esc(c.code)}</b> in ${esc(el.dataset.terr)}<br>${names.length ? esc(names.join(", ")) : "Nobody current. These repairs need a technician from another territory:"}${names.length ? "" : "<br>" + c.tasks.map(esc).join("<br>")}`;
    }
    const v = data.vans.find((x) => x.truck === el.dataset.van);
    const st = certState(v, c.code);
    const what = st.k === "none" ? "Not held" : st.k === "bad" ? "Expired" : st.k === "warn" ? `Expires in ${st.days} day${st.days === 1 ? "" : "s"}` : "Current";
    return `<b>${esc(v.name)}</b> · ${esc(c.name)} (${esc(c.body || "")})<br>${what}${st.h ? `<br>Certificate ${esc(st.h.number || "")}<br>${st.h.expires ? "Expires " + esc(fmtDate(st.h.expires, true)) : "Never expires"}` : ""}<br><span style="opacity:.8">Needed for: ${c.tasks.map(esc).join("; ")}</span>`;
  }

  function render(move) {
    renderKpis();
    renderCerts();
    drawStores();
    drawVans(move);
    renderList();
    renderDetail();
    $("f-updated").textContent = `Live from Atlas · ${new Date(data.generatedAt).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})}`;
  }

  function select(truck) {
    S.van = truck || null;
    writeHash();
    drawVans(false);
    renderList();
    renderDetail();
    renderCerts();
    const v = S.van && data.vans.find((x) => x.truck === S.van);
    drawTrail(v, true);
    if (!v) { trailLayer.clearLayers(); planLayer.clearLayers(); }
    if (v && window.matchMedia("(max-width: 960px)").matches) $("fmap").scrollIntoView({behavior: "smooth", block: "start"});
  }
  window.fleetSelect = (t) => { map.closePopup(); select(t); };
  window.fleetStore = (id) => {
    const m = storeMarkers[id];
    const s = storeById[id];
    if (!s) return;
    map.setView([s.lat, s.lon], Math.max(map.getZoom(), 11));
    if (m) m.openPopup();
  };

  // ---------- load ----------
  async function load() {
    const my = ++loadSeq;
    try {
      const r = await fetch("/api/fleet");
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.statusText);
      if (my !== loadSeq) return;
      const firstLoad = !data;
      data = j;
      storeById = Object.fromEntries(data.stores.map((s) => [s.id, s]));
      $("ft-err").style.display = "none";
      const sel = $("ft-terr");
      if (sel.options.length === 1) data.territories.forEach((t) => sel.add(new Option(t, t)));
      sel.value = S.terr;
      render(!firstLoad);
      if (firstLoad && S.van) drawTrail(data.vans.find((x) => x.truck === S.van), true);
      else if (firstLoad) fitTerritory();
      else if (S.van) drawTrail(data.vans.find((x) => x.truck === S.van), false);
    } catch (e) {
      $("ft-err").textContent = `Couldn't reach Atlas: ${e.message}`;
      $("ft-err").style.display = "block";
    }
  }
  function fitTerritory() {
    map.invalidateSize();
    const ss = data.stores.filter((s) => !S.terr || s.territory === S.terr);
    if (ss.length) map.fitBounds(L.latLngBounds(ss.map((s) => [s.lat, s.lon])).pad(0.1));
  }

  function wire() {
    if (wired) return;
    wired = true;
    $("ft-terr").addEventListener("change", (e) => { S.terr = e.target.value; writeHash(); render(false); fitTerritory(); });
    $("ft-q").addEventListener("input", (e) => { S.q = e.target.value; renderList(); });
    $("ft-status").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      S.status = b.dataset.s;
      writeHash();
      syncStatus();
      renderList();
    });
    const tip = $("ft-tip");
    $("ft-cmx").addEventListener("mouseover", (e) => {
      const el = e.target.closest("[data-tip]");
      if (!el || !data) { tip.hidden = true; return; }
      tip.innerHTML = certTip(el);
      tip.hidden = false;
      const b = el.getBoundingClientRect(), w = tip.offsetWidth;
      tip.style.left = Math.max(8, Math.min(innerWidth - w - 8, b.left + b.width / 2 - w / 2)) + "px";
      tip.style.top = (b.top - tip.offsetHeight - 8 < 8 ? b.bottom + 8 : b.top - tip.offsetHeight - 8) + "px";
    });
    $("ft-cmx").addEventListener("mouseleave", () => { tip.hidden = true; });
    window.addEventListener("scroll", () => { tip.hidden = true; }, {passive: true});
    const pick = (row) => { select(row.dataset.van); $("fmap").scrollIntoView({behavior: "smooth", block: "center"}); };
    $("ft-cmx").addEventListener("click", (e) => { const row = e.target.closest("tr.tech"); if (row) pick(row); });
    $("ft-cmx").addEventListener("keydown", (e) => { const row = e.target.closest("tr.tech"); if (row && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); pick(row); } });
    $("ft-list").addEventListener("click", (e) => {
      const b = e.target.closest(".vrow");
      if (b) select(b.dataset.van === S.van ? null : b.dataset.van);
    });
  }
  function syncStatus() { $("ft-status").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.s === S.status)); }

  function start() {
    if (starting) return starting;
    starting = (async () => {
      wire();
      syncStatus();
      if (!map) initMap();
      setTimeout(() => map.invalidateSize(), 60);
      if (data) {   // coming back to the tab or a hash change: apply the URL state
        $("ft-terr").value = S.terr;
        render(false);
        const v = S.van && data.vans.find((x) => x.truck === S.van);
        drawTrail(v, !!v);
      }
      await load();
      if (!timer) timer = setInterval(() => { if (!$("fleet").hidden) load(); }, 30000);
    })().finally(() => { starting = null; });
    return starting;
  }

  window.Fleet = {start, readHash};
})();
