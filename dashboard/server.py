#!/usr/bin/env python3
"""Soft Serve Finder - local dashboard server for the McDonald's Arkansas demo.

Serves dashboard/index.html and a small JSON API backed by live Atlas data (domain mcdonalds-ops, via the Atlas
Cypher REST endpoint and the Claude client-credentials token) plus the Arkansas ZIP centroids from Postgres.
Binds to 127.0.0.1 unless SWIRL_HOST says otherwise (SWIRL_HOST=0.0.0.0 to serve the LAN).

  python3 dashboard/server.py            -> http://127.0.0.1:8787
  GET /api/state      machines (store + live soft-serve state + reliability), technicians who could fix them
  GET /api/zip/72201  ZIP centroid
  GET /api/truck/track?truck=TRK-101[&hours=12]   a truck's road trail from Atlas (UNWIND over its GPS properties);
                      default: since local midnight
  GET /api/fleet      Fleet Tracker tab: every van (live GPS, status, who is driving, certifications, today's plan)
                      and every store with its worst live equipment condition
  Store Monitor tab (history from the Historian dataset McDonalds, live values from Atlas):
  GET /api/monitor/catalog                          stores, territories, equipment classes with state labels
  GET /api/monitor/current                          every unit's live state, signal, baseline, health, condition
  GET /api/monitor/fleet?stores=..&classes=..&hours=72   state runs + health index on a common time grid per unit
  GET /api/monitor/unit?store=AR-20031&cls=COOLER&hours=72   one unit in detail: signal, baseline, health, states
"""
import datetime as dt, json, os, subprocess, sys, threading, time, urllib.parse
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("SWIRL_PORT", "8787"))
HOST = os.environ.get("SWIRL_HOST", "127.0.0.1")
ATLAS_Q = "https://localhost:4552/api/v1/branches/main/domains/mcdonalds-ops/queries"
HIST = "https://localhost:4512/api/datasets/McDonalds"
HEADERS = os.path.expanduser("~/.claude/timebase-local-headers.sh")
TICKS_UNIX_EPOCH = 621355968000000000

Q_MACHINES = """
MATCH (t:Territory)-[:contains]->(s:Store)-[:contains]->(m) WHERE m.EquipmentClassCode = 'SOFTSERVE'
RETURN t.Name AS territory, s.StoreId AS id, s.Address AS address, s.City AS city, s.Zip AS zip,
       s.Latitude AS lat, s.Longitude AS lon, s.IsOpen AS open, s.OperatingStatus AS status, s.Phone AS phone,
       s.RestaurantHours AS hours, s.HasDriveThru AS driveThru,
       m.SoftServeState.Value AS state, m.SoftServeState.Timestamp AS since,
       m.IsServing.Value AS serving, m.CustomerHearsBroken.Value AS hearsBroken,
       m.Uptime24h.Value AS uptime24h, m.Uptime7d.Value AS uptime7d, m.Serving7d.Value AS serving7d,
       m.Failures7d.Value AS failures7d, m.MtbfHours.Value AS mtbf, m.MttrHours.Value AS mttr,
       m.DownMinutes.Value AS downMinutes, m.ReliabilityScore.Value AS score, m.ReliabilityGrade.Value AS grade,
       m.LostSalesUsd7d.Value AS lostUsd7d
"""
Q_TECHS = """
MATCH (tech:Technician)-[:basedAt]->(s:Store)
RETURN tech.TechnicianId AS id, tech.Name AS name, tech.CertLevel AS level, s.StoreId AS base, s.City AS baseCity,
       s.Latitude AS lat, s.Longitude AS lon
"""
Q_TRUCKS = """
MATCH (tech:Technician)-[:assignedTruck]->(k:ServiceTruck)
RETURN tech.TechnicianId AS id, k.TruckId AS truck, k.GpsLatitude.Value AS lat, k.GpsLongitude.Value AS lon,
       k.GpsLatitude.Timestamp AS fix, k.TruckStatus.Value AS status, k.CurrentStoreId.Value AS at,
       k.NextStoreId.Value AS next
"""
Q_TAYLOR = """
MATCH (tech:Technician)-[h:holdsCertification]->(c:Certification)
WHERE c.CertificationCode = 'TAYLOR' AND h.IsCurrent = true
RETURN tech.TechnicianId AS id
"""
Q_TAY_PARTS = """
MATCH (tech:Technician)-[:assignedTruck]->(k:ServiceTruck)-[cp:carriesPart]->(p:Part)
WHERE p.PartNumber IN ['P-TAY-KIT', 'P-TAY-BLADE'] AND cp.QuantityOnHand > 0
RETURN tech.TechnicianId AS id, k.TruckId AS truck, collect(p.PartNumber) AS parts
"""

_tok = {"v": None, "at": 0.0}
_cache = {"v": None, "at": 0.0}
_lock = threading.Lock()


def token():
    if not _tok["v"] or time.time() - _tok["at"] > 240:
        _tok["v"] = json.loads(subprocess.check_output([HEADERS]))["Authorization"]
        _tok["at"] = time.time()
    return _tok["v"]


def cypher(q):
    p = subprocess.run(["curl", "-sk", "--max-time", "60", "-X", "POST", "-H", "Authorization: " + token(),
                        "-H", "Content-Type: application/json", "--data-binary", "@-", ATLAS_Q],
                       input=json.dumps({"cypher": q}), capture_output=True, text=True)
    if p.returncode:   # the command line holds the bearer token - never surface it in an error or the page
        raise RuntimeError(f"Atlas query call failed (curl exit code {p.returncode})") from None
    out = p.stdout
    r = json.loads(out)
    if "columns" not in r:
        raise RuntimeError(f"Atlas query failed: {out[:300]}")
    return [dict(zip(r["columns"], row)) for row in r["data"]]


def ticks_to_iso(t):
    try:
        return dt.datetime.fromtimestamp((int(t) - TICKS_UNIX_EPOCH) / 1e7, dt.timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def load_zips():
    out = subprocess.run(["docker", "exec", "bible-pg", "psql", "-U", "bible_admin", "-d", "mcdonalds_ar", "-At", "-F", ",",
                          "-c", "SELECT zip, latitude, longitude FROM api.v_zip_code"], capture_output=True, text=True, check=True).stdout
    return {z: (float(a), float(b)) for z, a, b in (line.split(",") for line in out.splitlines() if line)}


ZIPS = load_zips()


def state():
    with _lock:
        if _cache["v"] and time.time() - _cache["at"] < 20:
            return _cache["v"]
        machines = cypher(Q_MACHINES)
        for m in machines:
            m["since"] = ticks_to_iso(m["since"])
        techs = {t["id"]: t for t in cypher(Q_TECHS)}
        for t in techs.values():
            t["taylorCertified"] = False
            t["taylorParts"] = False
        # Live truck GPS (Postgres route plan -> Connect -> Atlas). Distances use where the truck is now; the home
        # store stays as the fallback when a truck has no fix yet.
        for r in cypher(Q_TRUCKS):
            t = techs.get(r["id"])
            if not t:
                continue
            t["baseLat"], t["baseLon"], t["truck"] = t["lat"], t["lon"], r["truck"]
            if isinstance(r["lat"], (int, float)) and isinstance(r["lon"], (int, float)) and r["lat"]:
                t["lat"], t["lon"] = r["lat"], r["lon"]
                t["fix"] = ticks_to_iso(r["fix"])
            t["status"] = int(r["status"]) if isinstance(r["status"], (int, float)) else None
            t["at"], t["next"] = r["at"] or None, r["next"] or None
        for r in cypher(Q_TAYLOR):
            if r["id"] in techs:
                techs[r["id"]]["taylorCertified"] = True
        for r in cypher(Q_TAY_PARTS):
            if r["id"] in techs:
                techs[r["id"]]["truck"] = r["truck"]
                techs[r["id"]]["taylorParts"] = {"P-TAY-KIT", "P-TAY-BLADE"} <= set(r["parts"] or [])
        v = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
             "machines": sorted(machines, key=lambda m: m["id"]),
             "technicians": sorted(techs.values(), key=lambda t: t["id"])}
        _cache.update(v=v, at=time.time())
        return v


_tracks = {}
_fleet = {"v": None, "at": 0.0}
_fleet_lock = threading.Lock()

Q_FLEET = """
MATCH (tech:Technician)-[:assignedTruck]->(k:ServiceTruck)
RETURN tech.TechnicianId AS id, tech.Name AS name, tech.CertLevel AS level, tech.HomeStoreId AS home, tech.HireDate AS hired,
       k.TruckId AS truck, k.Make AS make, k.Model AS model, k.ModelYear AS year, k.LicensePlate AS plate,
       k.GpsLatitude.Value AS lat, k.GpsLongitude.Value AS lon, k.GpsLatitude.Timestamp AS fix,
       k.TruckStatus.Value AS status, k.CurrentStoreId.Value AS at, k.NextStoreId.Value AS next
"""
Q_FLEET_TERR = "MATCH (tech:Technician)-[:servesTerritory]->(t:Territory) RETURN tech.TechnicianId AS id, t.Name AS territory"
Q_FLEET_CERTS = """
MATCH (tech:Technician)-[h:holdsCertification]->(c:Certification)
RETURN tech.TechnicianId AS id, c.CertificationCode AS code, c.Name AS name, h.IsCurrent AS current,
       h.ExpiresDate AS expires, h.CertificateNumber AS number
"""
Q_CERT_CATALOG = """
MATCH (c:Certification) RETURN c.CertificationCode AS code, c.Name AS name, c.IssuingBody AS body
"""
Q_CERT_TASKS = """
MATCH (r:RepairTask)-[:requiresCertification]->(c:Certification)
RETURN c.CertificationCode AS code, r.Name AS task, r.EquipmentClassCode AS cls
"""


def _psql_rows(sql):
    out = subprocess.run(["docker", "exec", "bible-pg", "psql", "-U", "bible_admin", "-d", "mcdonalds_ar", "-At", "-F", "\t", "-c", sql],
                         capture_output=True, text=True, check=True).stdout
    return [line.split("\t") for line in out.splitlines() if line]


def fleet_tracker():
    """Fleet Tracker. Vans, drivers and live GPS come from Atlas; today's route plan and ETAs from the Postgres plan
    the GPS is derived from; stores and their equipment conditions from the Monitor's Atlas reads."""
    with _fleet_lock:
        if _fleet["v"] and time.time() - _fleet["at"] < 20:
            return _fleet["v"]
        with ThreadPoolExecutor(7) as ex:
            f_vans, f_terr, f_certs = ex.submit(cypher, Q_FLEET), ex.submit(cypher, Q_FLEET_TERR), ex.submit(cypher, Q_FLEET_CERTS)
            f_ccat, f_ctask = ex.submit(cypher, Q_CERT_CATALOG), ex.submit(cypher, Q_CERT_TASKS)
            f_cat, f_cur = ex.submit(catalog), ex.submit(current)
            vans, terr, certs, cat, cur = f_vans.result(), f_terr.result(), f_certs.result(), f_cat.result(), f_cur.result()
            ccat, ctask = f_ccat.result(), f_ctask.result()
        terr_of = {r["id"]: r["territory"] for r in terr}
        certs_of, held_of = {}, {}
        for r in certs:   # every certificate on record (current or lapsed); "certs" keeps only the current ones
            held_of.setdefault(r["id"], []).append({"code": r["code"], "current": r["current"] is True,
                                                    "expires": r["expires"] if r["expires"] not in (None, "", "never") else None,
                                                    "number": r["number"]})
            if r["current"] is True:
                certs_of.setdefault(r["id"], []).append({"code": r["code"], "name": r["name"]})
        tasks_of = {}
        for r in ctask:
            tasks_of.setdefault(r["code"], {"tasks": [], "classes": set()})
            tasks_of[r["code"]]["tasks"].append(r["task"])
            if r["cls"]:
                tasks_of[r["code"]]["classes"].add(r["cls"])
        cert_catalog = [{"code": c["code"], "name": c["name"], "body": c["body"],
                         "tasks": sorted(tasks_of.get(c["code"], {}).get("tasks", [])),
                         "classes": sorted(tasks_of.get(c["code"], {}).get("classes", set()))}
                        for c in sorted(ccat, key=lambda c: ["REFRIG", "EPA608", "HVAC", "GEN", "TAYLOR"].index(c["code"])
                                        if c["code"] in ("REFRIG", "EPA608", "HVAC", "GEN", "TAYLOR") else 99)]
        plan = {}
        for tid, seq, store, kind, arr, dep in _psql_rows(
                "SELECT technician_id, stop_seq, store_id, stop_kind, arrive_local, depart_local FROM api.v_route_stop "
                "WHERE rotation_day = (SELECT rotation_day FROM fleet.truck_position_at(now()) LIMIT 1) "
                "ORDER BY technician_id, stop_seq"):
            plan.setdefault(tid, []).append({"seq": int(seq), "store": store, "kind": kind, "arrive": arr, "depart": dep})
        eta = {tid: e for tid, e in _psql_rows(
            "SELECT technician_id, coalesce(to_char(eta_utc AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') "
            "FROM api.v_truck_position_live")}
        out_vans = []
        for v in vans:
            num = lambda x: x if isinstance(x, (int, float)) else None
            out_vans.append({
                "id": v["id"], "name": v["name"], "level": v["level"], "home": v["home"], "hired": v["hired"],
                "territory": terr_of.get(v["id"]), "certs": sorted(certs_of.get(v["id"], []), key=lambda c: c["code"]),
                "held": held_of.get(v["id"], []),
                "truck": v["truck"], "make": v["make"], "model": v["model"], "year": v["year"], "plate": v["plate"],
                "lat": num(v["lat"]), "lon": num(v["lon"]), "fix": ticks_to_iso(v["fix"]),
                "status": int(v["status"]) if num(v["status"]) is not None else None,
                "at": v["at"] or None, "next": v["next"] or None, "eta": eta.get(v["id"]) or None,
                "plan": plan.get(v["id"], [])})
        issues = {}
        for u in cur["units"]:
            if u.get("cond"):
                issues.setdefault(u["store"], []).append({"cls": u["cls"], "cond": u["cond"], "health": u.get("health")})
        stores = []
        for st in cat["stores"]:
            iss = sorted(issues.get(st["id"], []), key=lambda i: -i["cond"])
            stores.append({**st, "cond": iss[0]["cond"] if iss else 0, "issues": iss})
        v = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "vans": sorted(out_vans, key=lambda x: x["id"]),
             "stores": stores, "classes": {c["code"]: c["name"] for c in cat["classes"]},
             "territories": cat["territories"], "certCatalog": cert_catalog,
             "today": dt.datetime.now(ZoneInfo("America/Chicago")).date().isoformat()}
        _fleet.update(v=v, at=time.time())
        return v


def truck_track(q):
    """A truck's trail straight from Atlas: UNWIND over GpsLatitude / GpsLongitude / TruckStatus (Connect serves them
    from the Postgres route plan as time series). Points are [ms, lat, lon, status]."""
    import re
    truck = (q.get("truck") or [""])[0]
    if not re.fullmatch(r"TRK-\d{3}", truck):
        raise ValueError("truck must look like TRK-101")
    now = dt.datetime.now(dt.timezone.utc)
    if q.get("hours"):
        hours = float(q["hours"][0])
        if not 0 < hours <= 168:
            raise ValueError("hours must be between 0 and 168")
        start = now - dt.timedelta(hours=hours)
    else:   # since local midnight in Arkansas
        local = now.astimezone(ZoneInfo("America/Chicago"))
        start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc)
    key = (truck, start.isoformat()[:16])
    hit = _tracks.get(key)
    if hit and time.time() - hit[0] < 50:
        return hit[1]
    since = start.strftime("%Y-%m-%dT%H:%M:%SZ")

    def series(prop):
        rows = cypher(f"MATCH (k:ServiceTruck) WHERE k.TruckId = '{truck}' UNWIND k.{prop} AS v "
                      f"WITH v WHERE v.Timestamp >= datetime('{since}') RETURN v.Timestamp AS t, v.Value AS x")
        return {_ms(r["t"]): r["x"] for r in rows if _ms(r["t"]) is not None}
    with ThreadPoolExecutor(3) as ex:
        la, lo, st = ex.map(series, ("GpsLatitude", "GpsLongitude", "TruckStatus"))
    start_ms = int(start.timestamp() * 1000)
    pts = [[t, la[t], lo[t], int(st[t]) if isinstance(st.get(t), (int, float)) else None]
           for t in sorted(la) if t in lo and t >= start_ms - 1]
    out = {"truck": truck, "since": start.isoformat(), "points": pts}
    _tracks[key] = (time.time(), out)
    return out


# ======================================================================================================================
# Store Monitor
# ======================================================================================================================
Q_CURRENT = """
MATCH (t:Territory)-[:contains]->(s:Store)-[:contains]->(e)
RETURN s.StoreId AS store, e.EquipmentClassCode AS cls,
       e.RefrigerationState.Value AS s1, e.HVACState.Value AS s2, e.GeneratorState.Value AS s3, e.SoftServeState.Value AS s4,
       e.RefrigerationState.Timestamp AS t1, e.HVACState.Timestamp AS t2, e.GeneratorState.Timestamp AS t3,
       e.SoftServeState.Timestamp AS t4,
       e.Temperature.Value AS v1, e.SupplyAirTemperature.Value AS v2, e.LoadPercent.Value AS v3,
       e.HourlyAverage.Value AS avg1h, e.BaselineMean.Value AS bMean, e.BaselineStdDev.Value AS bSd,
       e.BaselineMode.Value AS bMode, e.HealthIndex.Value AS health, e.ServiceCondition.Value AS cond,
       e.ExposureUsd.Value AS exposure, e.ReliabilityGrade.Value AS grade, e.ReliabilityScore.Value AS score,
       e.Uptime24h.Value AS up24, e.Uptime7d.Value AS up7, e.Serving7d.Value AS serving7d, e.DownMinutes.Value AS downMin,
       e.Failures7d.Value AS failures7d, e.MtbfHours.Value AS mtbf, e.MttrHours.Value AS mttr,
       e.LostSalesUsd7d.Value AS lostUsd7d
"""
Q_STORES = """
MATCH (t:Territory)-[:contains]->(s:Store)
RETURN t.Name AS territory, s.StoreId AS id, s.Address AS address, s.City AS city, s.Zip AS zip,
       s.Latitude AS lat, s.Longitude AS lon, s.IsOpen AS open, s.OperatingStatus AS status
"""
GRID = 240                 # buckets on the fleet time grid
UNIT_BUCKETS = 480         # buckets for one unit's raw signal
HOURS_ALLOWED = (6, 24, 72, 168)
_mon = {"catalog": None, "current": None, "current_at": 0.0, "fleet": {}}
_mon_lock = threading.Lock()


def _ms(ts):
    """Historian ISO timestamp -> epoch ms (None for the 0001-01-01 'no earlier value' placeholder)."""
    y = int(ts[0:4])
    if y < 2000:
        return None
    base = dt.datetime(y, int(ts[5:7]), int(ts[8:10]), int(ts[11:13]), int(ts[14:16]), int(ts[17:19]),
                       tzinfo=dt.timezone.utc)
    frac = ts[20:].rstrip("Z") if len(ts) > 20 and ts[19] == "." else ""
    return int(base.timestamp()) * 1000 + (int((frac + "000")[:3]) if frac else 0)


def _iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hist_chunk(tags, start, end):
    q = urllib.parse.urlencode([("tagname", t) for t in tags] + [("start", _iso(start)), ("end", _iso(end))])
    p = subprocess.run(["curl", "-sk", "--max-time", "120", "-H", "Authorization: " + token(), HIST + "/data?" + q],
                       capture_output=True, text=True)
    if p.returncode:   # the command line holds the bearer token - never surface it
        raise RuntimeError(f"Historian read failed (curl exit code {p.returncode})") from None
    r = json.loads(p.stdout or "{}")
    out = {}
    for tl in r.get("tl", []):
        name = tl["t"] if isinstance(tl["t"], str) else tl["t"].get("n")
        pts = []
        for pt in tl.get("d", []):
            t = _ms(pt["t"])
            if t is None:
                continue
            v = pt.get("v")
            if not isinstance(v, (int, float)):
                # Quality 64 (Uncertain) points without a value arrive between state changes while the source keeps
                # running (the unit's temperature keeps logging). Treat them as "no new value": the state holds.
                # Anything else without a value (e.g. the Historian's shutdown marker, quality 28) is a real gap.
                if pt.get("q") == 64:
                    continue
                v = None
            pts.append((t, v))
        out[name] = pts
    return out


def hist(tags, start, end):
    """{tag: [(ms, value-or-None)]}; None = a point without a value (e.g. the Historian's shutdown marker)."""
    chunks = [tags[i:i + 40] for i in range(0, len(tags), 40)]
    res = {}
    with ThreadPoolExecutor(6) as ex:
        for part in ex.map(lambda c: _hist_chunk(c, start, end), chunks):
            res.update(part)
    return res


def catalog():
    if _mon["catalog"]:
        return _mon["catalog"]
    rows = subprocess.run(["docker", "exec", "bible-pg", "psql", "-U", "bible_admin", "-d", "mcdonalds_ar", "-At", "-F", "\t", "-c",
                           "SELECT equipment_class_code, name, tag_segment, coalesce(health_signal,''), "
                           "coalesce(normal_value::text,''), coalesce(normal_tolerance::text,''), coalesce(unit_of_measure,'') "
                           "FROM ref.equipment_class WHERE NOT is_deleted"],
                          capture_output=True, text=True, check=True).stdout
    order = ["COOLER", "FREEZER", "HVAC", "GENERATOR", "SOFTSERVE"]
    classes = {}
    for line in rows.splitlines():
        code, name, seg, sig, nv, nt, uom = line.split("\t")
        classes[code] = {"code": code, "name": name, "seg": seg, "signal": sig or None,
                         "normal": float(nv) if nv else None, "tol": float(nt) if nt else None, "unit": uom or None,
                         "states": {}}
    # state labels live on the Historian tags (one store is enough - every unit of a class shares them)
    p = subprocess.run(["curl", "-sk", "--max-time", "60", "-H", "Authorization: " + token(), HIST + "/tags"],
                       capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"Historian tag list failed (curl exit code {p.returncode})") from None
    by_seg = {c["seg"]: c for c in classes.values()}
    for tag in json.loads(p.stdout).get("User", []):
        parts = tag["n"].split(".")
        if len(parts) == 3 and parts[2] == "State" and parts[1] in by_seg and not by_seg[parts[1]]["states"]:
            by_seg[parts[1]]["states"] = {int(k): v for k, v in (tag.get("u") or {}).items()}
    stores = sorted(cypher(Q_STORES), key=lambda s: s["id"])
    _mon["catalog"] = {"stores": stores, "territories": sorted({s["territory"] for s in stores}),
                       "classes": [classes[c] for c in order if c in classes]}
    return _mon["catalog"]


def current():
    with _mon_lock:
        if _mon["current"] and time.time() - _mon["current_at"] < 20:
            return _mon["current"]
        units = []
        for r in cypher(Q_CURRENT):
            state = next((r[k] for k in ("s1", "s2", "s3", "s4") if r[k] is not None), None)
            since = next((r[k] for k in ("t1", "t2", "t3", "t4") if r[k] is not None), None)
            value = next((r[k] for k in ("v1", "v2", "v3") if r[k] is not None), None)
            u = {"store": r["store"], "cls": r["cls"], "state": state, "since": ticks_to_iso(since), "value": value}
            for k in ("avg1h", "bMean", "bSd", "bMode", "health", "cond", "exposure", "grade", "score", "up24", "up7",
                      "serving7d", "downMin", "failures7d", "mtbf", "mttr", "lostUsd7d"):
                u[k] = r[k]
            units.append(u)
        v = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "units": units}
        _mon.update(current=v, current_at=time.time())
        return v


def _health(avg, mean, sd, normal, tol):
    """Same formula as the Atlas function HealthIndexOf."""
    if avg is None or mean is None or sd is None or not tol:
        return None
    z = max((avg - mean) / max(sd, 1e-6), (avg - normal) / tol)
    return round(min(100.0, max(0.0, 100.0 - 25.0 * max(0.0, z - 1.0))), 1)


def _step(series):
    """Return f(t) giving the latest value at or before t (falls back to the first value)."""
    pts = [(t, v) for t, v in series if v is not None]
    idx = {"i": 0}

    def at(t):   # called with non-decreasing t
        i = idx["i"]
        while i + 1 < len(pts) and pts[i + 1][0] <= t:
            i += 1
        idx["i"] = i
        return pts[i][1] if pts else None
    return at


def health_series(cls, avg, mean, sd):
    mean_at, sd_at = _step(mean), _step(sd)
    out = []
    for t, v in avg:
        if v is None:
            continue
        h = _health(v, mean_at(t), sd_at(t), cls["normal"], cls["tol"])
        if h is not None:
            out.append((t, h))
    return out


def runs(points, start):
    """State points -> [[ms, code]] change list clipped to start (code None = no data)."""
    out, cur = [], "unset"
    for t, v in points:
        code = None if v is None else int(v)
        t = max(t, start)
        if code == cur:
            continue
        if out and out[-1][0] == t:
            out[-1][1] = code
        else:
            out.append([t, code])
        cur = code
    return out


def _grid_min(series, start, step, n, hold):
    """Worst (min) value per bucket; an empty bucket holds the previous value for up to `hold` ms."""
    g, last_t, last_v, i = [None] * n, None, None, 0
    pts = sorted(series)
    for b in range(n):
        lo, hi = start + b * step, start + (b + 1) * step
        best = None
        while i < len(pts) and pts[i][0] < hi:
            t, v = pts[i]
            if t >= lo:
                best = v if best is None else min(best, v)
            last_t, last_v = t, v
            i += 1
        if best is None and last_t is not None and lo - last_t <= hold:
            best = last_v
        g[b] = best
    return g


def _parse_hours(q):
    try:
        h = int(q.get("hours", ["72"])[0])
    except ValueError:
        h = 72
    return h if h in HOURS_ALLOWED else 72


class FleetHistory:
    """In-memory copy of the last 7 days of every unit's State, Avg1h and baseline tags.

    The first load reads ~3,000 tags (about half a minute against the Historian), so it runs in a background thread
    when the server starts; after that, refresh() reads only what arrived since the previous pass (every 60 s).
    """
    KEEP = (168 + 3) * 3600 * 1000
    SERIES = ("State", "Avg1h", "BaselineMean", "BaselineStdDev")

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}            # (store, cls) -> {series: [(ms, value)]}
        self.loaded_to = None     # ms up to which every tag has been read
        self.progress = 0.0
        self.error = None

    def _tags(self):
        cat = catalog()
        out = []          # (tag, store, cls, series)
        for c in cat["classes"]:
            for s in cat["stores"]:
                out.append((f"{s['id']}.{c['seg']}.State", s["id"], c["code"], "State"))
                if c["signal"]:
                    for k in ("Avg1h", "BaselineMean", "BaselineStdDev"):
                        out.append((f"{s['id']}.{c['seg']}.{c['signal']}{k}", s["id"], c["code"], k))
        return out

    def _read(self, start, end, report=False):
        tags = self._tags()
        names = [t[0] for t in tags]
        res = {}
        chunks = [names[i:i + 40] for i in range(0, len(names), 40)]
        with ThreadPoolExecutor(6) as ex:
            for n, part in enumerate(ex.map(lambda c: _hist_chunk(c, start, end), chunks), 1):
                res.update(part)
                if report:
                    self.progress = n / len(chunks)
        return tags, res

    def refresh(self):
        now = int(time.time() * 1000)
        first = self.loaded_to is None
        start = now - self.KEEP if first else self.loaded_to - 5 * 60 * 1000
        tags, res = self._read(start, now, report=first)
        with self.lock:
            for tag, store, cls, series in tags:
                d = self.data.setdefault((store, cls), {})
                cur = d.get(series, [])
                last = cur[-1][0] if cur else None
                new = [p for p in res.get(tag, []) if last is None or p[0] > last]
                cur = [p for p in cur + new if p[0] >= now - self.KEEP]
                # keep the latest point before the window so step-held values (state, baseline) stay known
                older = [p for p in (d.get(series) or []) if p[0] < now - self.KEEP]
                d[series] = older[-1:] + cur
            self.loaded_to = now
            self.progress = 1.0

    def loop(self):
        while True:
            try:
                self.refresh()
                self.error = None
            except Exception as e:   # keep serving what we have; the page shows the error if nothing loaded
                self.error = str(e)[:300]
            time.sleep(60)

    def ready(self):
        return self.loaded_to is not None


HISTORY = FleetHistory()


def fleet(q):
    cat = catalog()
    classes = {c["code"]: c for c in cat["classes"]}
    known = {s["id"] for s in cat["stores"]}
    stores = [s for s in q.get("stores", [""])[0].split(",") if s in known] or sorted(known)
    want = [c for c in q.get("classes", [""])[0].split(",") if c in classes] or list(classes)
    hours = _parse_hours(q)
    if not HISTORY.ready():
        return {"loading": True, "progress": round(HISTORY.progress, 2), "error": HISTORY.error}
    key = (tuple(stores), tuple(want), hours, HISTORY.loaded_to)
    with _mon_lock:
        hit = _mon["fleet"].get(key)
        if hit:
            return hit
    end = HISTORY.loaded_to
    start = end - hours * 3600 * 1000
    step = (end - start) // GRID
    units = []
    with HISTORY.lock:
        for s in stores:
            for c in want:
                cl = classes[c]
                d = HISTORY.data.get((s, c), {})
                u = {"store": s, "cls": c, "states": runs(d.get("State", []), start)}
                if cl["signal"]:
                    avg = [p for p in d.get("Avg1h", []) if p[0] >= start - 3600 * 1000]
                    hs = health_series(cl, avg, d.get("BaselineMean", []), d.get("BaselineStdDev", []))
                    u["health"] = _grid_min(hs, start, step, GRID, 30 * 60 * 1000)
                units.append(u)
    v = {"start": start, "end": end, "step": step, "hours": hours, "units": units}
    with _mon_lock:
        if len(_mon["fleet"]) > 40:
            _mon["fleet"].clear()
        _mon["fleet"][key] = v
    return v


def unit(q):
    cat = catalog()
    classes = {c["code"]: c for c in cat["classes"]}
    store, c = q.get("store", [""])[0], q.get("cls", [""])[0]
    if store not in {s["id"] for s in cat["stores"]} or c not in classes:
        raise ValueError("unknown store or equipment class")
    cl = classes[c]
    seg, sig = cl["seg"], cl["signal"]
    hours = _parse_hours(q)
    end = int(time.time() * 1000)
    start = end - hours * 3600 * 1000
    tags = [f"{store}.{seg}.State"]
    if sig:
        tags += [f"{store}.{seg}.{sig}", f"{store}.{seg}.{sig}Avg1h", f"{store}.{seg}.{sig}BaselineMean",
                 f"{store}.{seg}.{sig}BaselineStdDev"]
    data = hist(tags, start - 2 * 3600 * 1000, end)
    out = {"store": store, "cls": c, "start": start, "end": end, "hours": hours,
           "states": runs(data.get(f"{store}.{seg}.State", []), start)}
    if sig:
        raw = [(t, v) for t, v in data.get(f"{store}.{seg}.{sig}", []) if v is not None and t >= start]
        step = (end - start) / UNIT_BUCKETS
        buckets = {}
        for t, v in raw:
            b = min(UNIT_BUCKETS - 1, int((t - start) / step))
            x = buckets.get(b)
            if x is None:
                buckets[b] = [v, v, v, 1]
            else:
                x[0] = min(x[0], v); x[1] = max(x[1], v); x[2] += v; x[3] += 1
        out["signal"] = [[int(start + (b + 0.5) * step), round(x[0], 2), round(x[2] / x[3], 2), round(x[1], 2)]
                         for b, x in sorted(buckets.items())]
        clip = lambda series: [[max(t, start), round(v, 3)] for t, v in series if v is not None and t >= start - 2 * 3600 * 1000]
        avg = data.get(f"{store}.{seg}.{sig}Avg1h", [])
        mean = data.get(f"{store}.{seg}.{sig}BaselineMean", [])
        sd = data.get(f"{store}.{seg}.{sig}BaselineStdDev", [])
        out["avg1h"] = [p for p in clip(avg) if p[0] >= start]
        out["bMean"], out["bSd"] = clip(mean), clip(sd)
        out["health"] = [[t, h] for t, h in health_series(cl, avg, mean, sd) if t >= start]
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path in ("/", "/index.html"):
                with open(os.path.join(HERE, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if path == "/monitor.js":
                with open(os.path.join(HERE, "monitor.js"), "rb") as f:
                    return self._send(200, f.read(), "text/javascript; charset=utf-8")
            if path == "/api/state":
                return self._send(200, state())
            if path.startswith("/api/monitor/"):
                q = urllib.parse.parse_qs(self.path.partition("?")[2])
                what = path.rsplit("/", 1)[-1]
                fn = {"catalog": lambda: catalog(), "current": lambda: current(), "fleet": lambda: fleet(q),
                      "unit": lambda: unit(q)}.get(what)
                if not fn:
                    return self._send(404, {"error": "not found"})
                try:
                    return self._send(200, fn())
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
            if path == "/api/fleet":
                return self._send(200, fleet_tracker())
            if path == "/fleet.js":
                with open(os.path.join(HERE, "fleet.js"), "rb") as f:
                    return self._send(200, f.read(), "text/javascript; charset=utf-8")
            if path == "/api/truck/track":
                try:
                    return self._send(200, truck_track(urllib.parse.parse_qs(self.path.partition("?")[2])))
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
            if path.startswith("/api/zip/"):
                z = path.rsplit("/", 1)[-1]
                if z in ZIPS:
                    return self._send(200, {"zip": z, "lat": ZIPS[z][0], "lon": ZIPS[z][1]})
                return self._send(404, {"error": f"{z} isn't an Arkansas ZIP we know (try 72201, 72701 or 71601)"})
            return self._send(404, {"error": "not found"})
        except Exception as e:   # surface Atlas/DB problems to the page instead of a dropped connection
            return self._send(502, {"error": str(e)[:400]})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    threading.Thread(target=HISTORY.loop, daemon=True).start()
    print(f"Soft Serve Finder on http://{HOST}:{PORT}  ({len(ZIPS)} ZIPs loaded)", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
