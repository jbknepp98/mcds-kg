#!/usr/bin/env python3
"""Plan every technician's daily truck route on real Arkansas roads and write sql/13_routes_data.sql.

Needs the Valhalla routing server from ~/arkansas-routing (OpenStreetMap Arkansas extract) on localhost:8002:
    cd ~/arkansas-routing && docker compose up -d valhalla
It is only needed while planning; the demo itself reads the stored plan.

Each workday of a ROTATION_DAYS rotation (anchored on a Monday), every technician leaves their home store between
07:15 and 08:00, works 3-4 service stops plus a lunch stop at stores in their own part of the territory, and drives
home. Valhalla orders the stops (optimized_route) and supplies the road shape and maneuver times for every leg.
Weekends have no stops, so trucks stay parked at the home store. Seeded per technician and day: re-running gives
the same plan unless the stores, technicians or road data change.

    python3 tools/plan_routes.py            # plan, write the SQL file, load it into mcdonalds_ar
    python3 tools/plan_routes.py --no-load  # plan and write only
"""
import datetime as dt, json, math, os, random, subprocess, sys, urllib.request

sys.setrecursionlimit(20000)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "sql", "13_routes_data.sql")
VALHALLA = "http://localhost:8002"
ANCHOR = dt.date(2026, 11, 2)          # a Monday; rotation day 0
ROTATION_DAYS = 21
TZ = "America/Chicago"
OSM = "arkansas-latest.osm.pbf (Geofabrik, tiles built 2026-09-11)"
SIMPLIFY_M = 12                        # keep road shape to within ~12 m
DAY_END_EARLIEST = 15 * 3600            # add a stop if the day would end before 15:00
DAY_END_LATEST = 17 * 3600 + 45 * 60   # drop one if it would run past 17:45
OWN_RADIUS_MI = 70                     # straight-line reach for a technician's own patch
HELP_RADIUS_MI = 45                    # and for helping out elsewhere in the territory

PSQL = ["docker", "exec", "-i", "bible-pg", "psql", "-v", "ON_ERROR_STOP=1", "-q", "-U", "bible_admin", "-d", "mcdonalds_ar"]


def sql_rows(q):
    out = subprocess.run(PSQL + ["-At", "-F", "\t", "-c", q], capture_output=True, text=True, check=True).stdout
    return [l.split("\t") for l in out.splitlines() if l]


def hav_m(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def decode6(s):
    i = lat = lon = 0
    out = []
    while i < len(s):
        for k in (0, 1):
            sh = r = 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                r |= (b & 0x1F) << sh
                sh += 5
                if b < 0x20:
                    break
            d = ~(r >> 1) if r & 1 else r >> 1
            if k == 0:
                lat += d
            else:
                lon += d
        out.append((lat / 1e6, lon / 1e6))
    return out


def rdp(idx, pts, eps):
    """Ramer-Douglas-Peucker on indexes into pts (equirectangular metres is plenty at road scale)."""
    if len(idx) < 3:
        return idx
    a, b = pts[idx[0]], pts[idx[-1]]
    k = math.cos(math.radians(a[0])) * 111320
    ax, ay, bx, by = a[1] * k, a[0] * 110540, b[1] * k, b[0] * 110540
    dx, dy = bx - ax, by - ay
    L = math.hypot(dx, dy) or 1e-9
    worst, wi = -1, None
    for j in idx[1:-1]:
        px, py = pts[j][1] * k, pts[j][0] * 110540
        d = abs(dy * px - dx * py + bx * ay - by * ax) / L if L > 1e-6 else math.hypot(px - ax, py - ay)
        if d > worst:
            worst, wi = d, j
    if worst <= eps:
        return [idx[0], idx[-1]]
    m = idx.index(wi)
    return rdp(idx[:m + 1], pts, eps)[:-1] + rdp(idx[m:], pts, eps)


def leg_shape(leg):
    """Road points with seconds-after-departure, using each maneuver's own time spread by distance."""
    pts = decode6(leg["shape"])
    off = [0.0] * len(pts)
    for m in leg["maneuvers"]:
        b, e, t = m["begin_shape_index"], m["end_shape_index"], m["time"]
        if e <= b:
            continue
        seg = [hav_m(pts[j], pts[j + 1]) for j in range(b, e)]
        tot = sum(seg) or 1.0
        acc = 0.0
        for j in range(b, e):
            acc += seg[j - b]
            off[j + 1] = off[b] + t * acc / tot
    keep = rdp(list(range(len(pts))), pts, SIMPLIFY_M)
    return [(round(pts[j][0], 5), round(pts[j][1], 5), int(round(off[j]))) for j in keep]


def valhalla(locs):
    body = {"locations": [{"lat": a, "lon": o} for a, o in locs], "costing": "auto", "units": "miles"}
    req = urllib.request.Request(VALHALLA + "/optimized_route", json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))["trip"]


def main():
    try:
        urllib.request.urlopen(VALHALLA + "/status", timeout=5).read()
    except Exception:
        sys.exit("Valhalla is not answering on localhost:8002 - run: cd ~/arkansas-routing && docker compose up -d valhalla")

    stores = {r[0]: (r[1], float(r[2]), float(r[3])) for r in sql_rows(
        "SELECT store_id, territory_id, latitude, longitude FROM org.store WHERE NOT is_deleted ORDER BY store_id")}
    techs = sql_rows("SELECT technician_id, home_territory_id, home_store_id FROM hr.technician WHERE NOT is_deleted ORDER BY technician_id")

    # Each technician's patch: territory stores nearest their home store (ties to the lower technician id).
    patch = {t[0]: [] for t in techs}
    for sid, (terr, la, lo) in stores.items():
        mates = [t for t in techs if t[1] == terr]
        if mates:
            best = min(mates, key=lambda t: (hav_m((la, lo), stores[t[2]][1:]), t[0]))
            patch[best[0]].append(sid)

    MI = 1609.344
    stop_rows, leg_rows = [], []
    for tid, terr, home in techs:
        hpos = stores[home][1:]
        own = [s for s in patch[tid] if s != home and hav_m(hpos, stores[s][1:]) <= OWN_RADIUS_MI * MI]
        wider = [s for s, v in stores.items() if v[0] == terr and s != home and s not in patch[tid]
                 and hav_m(hpos, v[1:]) <= HELP_RADIUS_MI * MI]
        for day in range(ROTATION_DAYS):
            if day % 7 >= 5:
                continue                                           # weekend: parked at home
            rnd = random.Random(f"{tid}|{day}")
            cands = rnd.sample(own, len(own))
            extra = rnd.sample(wider, len(wider))
            if extra and rnd.random() < 0.25:
                cands.insert(rnd.randint(0, min(2, len(cands))), extra.pop())   # now and then, help out nearby
            cands += extra
            n = min(rnd.choice([3, 4, 4]), len(cands))
            works = [rnd.randint(40, 105) * 60 for _ in range(8)]
            admin = [rnd.randint(2, 8) * 60 for _ in range(8)]
            lunch = rnd.randint(30, 40) * 60
            depart0 = rnd.randint(7 * 3600 + 900, 8 * 3600) // 60 * 60
            tried = {}
            while True:
                picks = cands[:n]
                if n not in tried:
                    locs = [hpos] + [stores[x][1:] for x in picks] + [hpos]
                    trip = valhalla(locs)
                    order = [l["original_index"] for l in trip["locations"]]
                    tried[n] = ([home] + [picks[i - 1] for i in order[1:-1]] + [home], trip["legs"])
                seq, legs = tried[n]
                drive_total = sum(l["summary"]["time"] for l in legs)
                work_total = sum(works[:n]) + sum(admin[:n]) + lunch
                end = depart0 + drive_total + work_total
                if end > DAY_END_LATEST and n > 2:
                    n -= 1
                    continue
                if end < DAY_END_EARLIEST and n < min(5, len(cands)) and n + 1 not in tried:
                    n += 1
                    continue
                break
            # A thin patch can leave the day short: stretch the jobs so the truck gets home around 15:00-16:00.
            target = DAY_END_EARLIEST + rnd.randint(0, 60) * 60
            scale = max(1.0, (target - depart0 - drive_total - sum(admin[:n]) - lunch) / max(1, sum(works[:n])))
            t, stops, lunch_done, plan_legs, k = depart0, [(0, home, "START", depart0 - 1800, depart0)], False, [], 0
            for i, leg in enumerate(legs):
                dest = seq[i + 1]
                k += 1
                drive = max(60, int(round(leg["summary"]["time"])))
                plan_legs.append((k, seq[i], dest, t, drive, round(leg["summary"]["length"], 1), leg_shape(leg)))
                t += drive
                if i == len(legs) - 1:
                    stops.append((k, dest, "END", t, t))
                    break
                work = int(works[i] * scale) // 60 * 60
                stops.append((k, dest, "SERVICE", t, t + work))
                t += work
                if not lunch_done and t >= 11 * 3600 + 900:     # lunch at the first job that ends after 11:15
                    k += 1
                    stops.append((k, dest, "LUNCH", t, t + lunch))
                    t += lunch
                    lunch_done = True
                t += admin[i]                                   # paperwork before pulling out
            for k, sid, kind, a, d in stops:
                stop_rows.append((tid, day, k, sid, kind, max(0, a), d))
            for k, fr, to, dep, drive, miles, shape in plan_legs:
                leg_rows.append((tid, day, k, fr, to, dep, drive, miles, shape))
        print(f"{tid}: planned ({len(own)} stores within {OWN_RADIUS_MI} mi, {len(wider)} to help with)", flush=True)

    def rid(tid, day, k):
        return f"{tid}|D{day:02d}|{k:02d}"

    w = []
    w.append("-- GENERATED by tools/plan_routes.py - do not edit by hand. Run as mcd_admin after 13_routes.sql. Re-runnable:")
    w.append("-- rows are upserted, and any stop or leg no longer in the plan is soft-deleted.")
    w.append(f"INSERT INTO fleet.route_setting (route_setting_id, anchor_date, rotation_days, time_zone, planned_utc, osm_extract) VALUES "
             f"('DEFAULT', '{ANCHOR}', {ROTATION_DAYS}, '{TZ}', '{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M:%S}+00', '{OSM}')")
    w.append("ON CONFLICT (route_setting_id) DO UPDATE SET anchor_date = EXCLUDED.anchor_date, rotation_days = EXCLUDED.rotation_days,"
             " time_zone = EXCLUDED.time_zone, planned_utc = EXCLUDED.planned_utc, osm_extract = EXCLUDED.osm_extract, is_deleted = false, deleted_utc = NULL;")
    w.append("BEGIN;")
    w.append("CREATE TEMP TABLE _stop (LIKE fleet.route_stop INCLUDING DEFAULTS) ON COMMIT DROP;")
    w.append("CREATE TEMP TABLE _leg (LIKE fleet.route_leg INCLUDING DEFAULTS) ON COMMIT DROP;")
    w.append("INSERT INTO _stop (route_stop_id, technician_id, rotation_day, stop_seq, store_id, stop_kind, arrive_sec, depart_sec) VALUES")
    w.append(",\n".join(f"('{rid(t, d, k)}','{t}',{d},{k},'{s}','{kind}',{a},{dd})" for t, d, k, s, kind, a, dd in stop_rows) + ";")
    for i in range(0, len(leg_rows), 200):
        w.append("INSERT INTO _leg (route_leg_id, technician_id, rotation_day, stop_seq, from_store_id, to_store_id, depart_sec, drive_sec, road_miles, lat, lon, offset_sec) VALUES")
        w.append(",\n".join(
            f"('{rid(t, d, k)}','{t}',{d},{k},'{fr}','{to}',{dep},{drive},{miles},"
            f"'{{{','.join(str(p[0]) for p in sh)}}}','{{{','.join(str(p[1]) for p in sh)}}}','{{{','.join(str(p[2]) for p in sh)}}}')"
            for t, d, k, fr, to, dep, drive, miles, sh in leg_rows[i:i + 200]) + ";")
    w.append("""INSERT INTO fleet.route_stop (route_stop_id, technician_id, rotation_day, stop_seq, store_id, stop_kind, arrive_sec, depart_sec)
SELECT route_stop_id, technician_id, rotation_day, stop_seq, store_id, stop_kind, arrive_sec, depart_sec FROM _stop
ON CONFLICT (route_stop_id) DO UPDATE SET store_id = EXCLUDED.store_id, stop_kind = EXCLUDED.stop_kind,
  arrive_sec = EXCLUDED.arrive_sec, depart_sec = EXCLUDED.depart_sec, is_deleted = false, deleted_utc = NULL
  WHERE (fleet.route_stop.store_id, fleet.route_stop.stop_kind, fleet.route_stop.arrive_sec, fleet.route_stop.depart_sec, fleet.route_stop.is_deleted)
        IS DISTINCT FROM (EXCLUDED.store_id, EXCLUDED.stop_kind, EXCLUDED.arrive_sec, EXCLUDED.depart_sec, false);
INSERT INTO fleet.route_leg (route_leg_id, technician_id, rotation_day, stop_seq, from_store_id, to_store_id, depart_sec, drive_sec, road_miles, lat, lon, offset_sec)
SELECT route_leg_id, technician_id, rotation_day, stop_seq, from_store_id, to_store_id, depart_sec, drive_sec, road_miles, lat, lon, offset_sec FROM _leg
ON CONFLICT (route_leg_id) DO UPDATE SET from_store_id = EXCLUDED.from_store_id, to_store_id = EXCLUDED.to_store_id,
  depart_sec = EXCLUDED.depart_sec, drive_sec = EXCLUDED.drive_sec, road_miles = EXCLUDED.road_miles,
  lat = EXCLUDED.lat, lon = EXCLUDED.lon, offset_sec = EXCLUDED.offset_sec, is_deleted = false, deleted_utc = NULL
  WHERE (fleet.route_leg.from_store_id, fleet.route_leg.to_store_id, fleet.route_leg.depart_sec, fleet.route_leg.drive_sec,
         fleet.route_leg.road_miles, fleet.route_leg.lat, fleet.route_leg.lon, fleet.route_leg.offset_sec, fleet.route_leg.is_deleted)
        IS DISTINCT FROM (EXCLUDED.from_store_id, EXCLUDED.to_store_id, EXCLUDED.depart_sec, EXCLUDED.drive_sec,
         EXCLUDED.road_miles, EXCLUDED.lat, EXCLUDED.lon, EXCLUDED.offset_sec, false);
UPDATE fleet.route_leg SET is_deleted = true, deleted_utc = now()
 WHERE NOT is_deleted AND route_leg_id NOT IN (SELECT route_leg_id FROM _leg);
UPDATE fleet.route_stop SET is_deleted = true, deleted_utc = now()
 WHERE NOT is_deleted AND route_stop_id NOT IN (SELECT route_stop_id FROM _stop);
COMMIT;""")
    text = "\n".join(w) + "\n"
    open(OUT, "w").write(text)
    pts = sum(len(l[8]) for l in leg_rows)
    print(f"wrote {OUT}: {len(stop_rows)} stops, {len(leg_rows)} legs, {pts} road points, {len(text) / 1e6:.1f} MB")
    if "--no-load" not in sys.argv:
        subprocess.run(PSQL, input="SET ROLE mcd_admin;\n" + text, text=True, check=True)
        print("loaded into mcdonalds_ar")


if __name__ == "__main__":
    main()
