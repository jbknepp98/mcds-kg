#!/usr/bin/env python3
"""Soft Serve Finder - local dashboard server for the McDonald's Arkansas demo.

Serves dashboard/index.html and a small JSON API backed by live Atlas data (domain mcdonalds-ops, via the Atlas
Cypher REST endpoint and the Claude client-credentials token) plus the Arkansas ZIP centroids from Postgres.
Binds to 127.0.0.1 only.

  python3 dashboard/server.py            -> http://127.0.0.1:8787
  GET /api/state      machines (store + live soft-serve state + reliability), technicians who could fix them
  GET /api/zip/72201  ZIP centroid
"""
import datetime as dt, json, os, subprocess, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("SWIRL_PORT", "8787"))
ATLAS_Q = "https://localhost:4552/api/v1/branches/main/domains/mcdonalds-ops/queries"
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
    out = subprocess.run(["curl", "-sk", "--max-time", "60", "-X", "POST", "-H", "Authorization: " + token(),
                          "-H", "Content-Type: application/json", "--data-binary", "@-", ATLAS_Q],
                         input=json.dumps({"cypher": q}), capture_output=True, text=True, check=True).stdout
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
            if path == "/api/state":
                return self._send(200, state())
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
    print(f"Soft Serve Finder on http://127.0.0.1:{PORT}  ({len(ZIPS)} ZIPs loaded)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
