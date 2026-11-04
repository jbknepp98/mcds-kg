#!/usr/bin/env python3
"""McDonald's Arkansas health baseline job.

Reads the simulator signals from the local Historian (dataset McDonalds), works out each unit's
baseline and its latest 1-hour average, and writes them back as Historian tags that Atlas binds.
The health index itself is calculated in Atlas (function HealthIndex); this job only supplies
inputs that Atlas cannot compute (Atlas functions see one point in time, not a window).

Per unit and signal it writes four tags, e.g. for AR-20031's cooler:
  AR-20031.Cooler.TemperatureAvg1h            mean of the most recent hour of steady-state operation
  AR-20031.Cooler.TemperatureBaselineMean     baseline the 1-hour average is compared with
  AR-20031.Cooler.TemperatureBaselineStdDev   spread of that baseline
  AR-20031.Cooler.TemperatureBaselineMode     1 = the unit's own 3-day baseline, 0 = defined normal operation

Rules:
  * Steady state = the class's steady_state_codes (ref.equipment_class), e.g. Holding (20) for coolers.
    Defrost, door-open, stocking and fault periods are left out of both the baseline and the average.
  * Baseline = mean / stdev of the hourly steady-state means over the last 3 days. Needs at least
    MIN_HOURS hours with steady data and some real variation; otherwise the unit falls back to the
    class's defined normal (normal_value / normal_tolerance) - e.g. a generator that sat in standby.
  * Avg1h = mean of steady samples in the last 60 minutes; if the unit has not been in a steady state
    for that long, the mean of its most recent hour of steady operation; if it has had none in 3 days
    (generator in standby), the plain mean of the last hour.

Soft serve reliability (machines only report a state code): from 7 days of <Store>.SoftServe.State history it writes
  Uptime24h, Uptime7d    % of the window NOT in a fault (state 40, Needs Service)
  Serving7d              % of the window actually serving (state 0; heat treat and mix low count against it)
  Failures7d             times the machine entered a fault in the window
  MtbfHours, MttrHours   mean time between failures / to repair over the window (MTBF = window when no failures)
  DownMinutes            length of the current outage (0 when not faulted)
  DownHours7d            hours in fault over the window (lost-sales input)
Atlas turns these into ReliabilityScore / ReliabilityGrade / LostSalesUsd7d.

Also rolls the truck inventory forward: CALL fleet.generate_inventory(today) (idempotent), and on the first run of
each local day recompiles the Atlas domain so truck stock and certification currency refresh.

Usage:
  health_baseline.py                 one run: Avg1h every run, baselines when the last is > 55 min old
  health_baseline.py --backfill 24   also write history: Avg1h every 5 min and baselines hourly
  health_baseline.py --dry-run       compute and print a summary, write nothing
"""
import argparse, datetime as dt, json, os, statistics as st, subprocess, sys, urllib.parse

HIST = "https://localhost:4512/api/datasets/McDonalds"
ATLAS_WORLD = "https://localhost:4552/api/v1/branches/main/domains/mcdonalds-ops/world"
HEADERS = os.path.expanduser("~/.claude/timebase-local-headers.sh")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".health_baseline_state.json")
BASELINE_DAYS = 3
MIN_HOURS = 24            # hours with steady data needed for a self-baseline
MIN_SAMPLES_PER_HOUR = 20
MIN_VARIATION = 0.05      # stdev of hourly means below this = "no variation"
SD_FLOOR_FRACTION = 0.5   # self-baseline stdev is floored at this fraction of the normal tolerance
BATCH = 20
HEARTBEAT = dt.timedelta(minutes=40)   # re-stamp a state tag's held value when it is older than this (see heartbeat())
UTC = dt.timezone.utc


def psql(sql):
    out = subprocess.run(["docker", "exec", "-i", "bible-pg", "psql", "-v", "ON_ERROR_STOP=1", "-qAt", "-F", "\t",
                          "-U", "bible_admin", "-d", "mcdonalds_ar"], input="SET ROLE mcd_admin;\n" + sql,
                         capture_output=True, text=True, check=True)
    return [line.split("\t") for line in out.stdout.splitlines() if line]


def token():
    return json.loads(subprocess.check_output([HEADERS]))["Authorization"]


def curl(tok, method, url, body=None):
    cmd = ["curl", "-sk", "-X", method, "-H", "Authorization: " + tok, "--max-time", "300"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
    out = subprocess.run(cmd + [url], input=body, capture_output=True, text=True, check=True).stdout
    return json.loads(out) if out.strip() else None


def iso(t):
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse(ts):
    ts = ts.rstrip("Z")
    if "." in ts:
        head, frac = ts.split(".")
        ts = head + "." + (frac + "000000")[:6]
    return dt.datetime.fromisoformat(ts).replace(tzinfo=UTC)


def read(tok, tags, start, end):
    q = urllib.parse.urlencode([("tagname", t) for t in tags] + [("start", iso(start)), ("end", iso(end))])
    r = curl(tok, "GET", HIST + "/data?" + q)
    res = {}
    for tl in r.get("tl", []):
        name = tl["t"] if isinstance(tl["t"], str) else tl["t"].get("n")
        res[name] = [(parse(p["t"]), p["v"]) for p in tl.get("d", []) if isinstance(p.get("v"), (int, float))]
    return res


def steady_samples(signal, states, codes):
    """Signal points whose step-held state (latest state at or before the point) is in codes."""
    out, i, cur = [], 0, None
    for t, v in signal:
        while i < len(states) and states[i][0] <= t:
            cur = int(states[i][1]); i += 1
        if cur is not None and cur in codes:
            out.append((t, v))
    return out


def baseline(steady, at, normal, tol):
    lo = at - dt.timedelta(days=BASELINE_DAYS)
    hours = {}
    for t, v in steady:
        if lo <= t <= at:
            hours.setdefault(t.replace(minute=0, second=0, microsecond=0), []).append(v)
    means = [st.mean(v) for v in hours.values() if len(v) >= MIN_SAMPLES_PER_HOUR]
    if len(means) >= MIN_HOURS and st.pstdev(means) >= MIN_VARIATION:
        return st.mean(means), max(st.pstdev(means), SD_FLOOR_FRACTION * tol), 1
    return normal, tol, 0


def avg1h(steady, signal, at):
    hour = [v for t, v in steady if at - dt.timedelta(hours=1) < t <= at]
    if len(hour) >= MIN_SAMPLES_PER_HOUR:
        return st.mean(hour)
    past = [(t, v) for t, v in steady if t <= at]
    if past:   # most recent hour of steady operation
        last = past[-1][0]
        return st.mean(v for t, v in past if t > last - dt.timedelta(hours=1))
    recent = [v for t, v in signal if at - dt.timedelta(hours=1) < t <= at]   # no steady data in reach
    if recent:
        return st.mean(recent)
    prior = [v for t, v in signal if t <= at]
    return prior[-1] if prior else None


SS_FIELDS = ("Uptime24h", "Uptime7d", "Serving7d", "Failures7d", "MtbfHours", "MttrHours", "DownMinutes", "DownHours7d")


def softserve_metrics(states, at):
    """states: step-held [(t, code)] sorted, first point may precede the window. Returns dict of SS_FIELDS."""
    def share(lo, pred):
        tot = 0.0
        for i, (t, v) in enumerate(states):
            t1 = states[i + 1][0] if i + 1 < len(states) else at
            a, b = max(t, lo), min(t1, at)
            if b > a and pred(int(v)):
                tot += (b - a).total_seconds()
        return tot / (at - lo).total_seconds()
    pts = [(t, v) for t, v in states if t <= at]
    if not pts:
        return None
    states = pts
    w7, w1 = at - dt.timedelta(days=7), at - dt.timedelta(days=1)
    fault7 = share(w7, lambda c: c >= 40)
    fails = sum(1 for i in range(1, len(states)) if states[i][0] >= w7
                and int(states[i][1]) >= 40 and int(states[i - 1][1]) < 40)
    # (an outage already running when the window opened is not counted as a new failure)
    down_min = 0.0
    if int(states[-1][1]) >= 40:
        start = states[-1][0]
        for t, v in reversed(states):
            if int(v) < 40:
                break
            start = t
        down_min = (at - start).total_seconds() / 60
    hours7 = 7 * 24
    return {"Uptime24h": round(100 * (1 - share(w1, lambda c: c >= 40)), 2),
            "Uptime7d": round(100 * (1 - fault7), 2),
            "Serving7d": round(100 * share(w7, lambda c: c == 0), 2),
            "Failures7d": fails,
            "MtbfHours": round(hours7 * (1 - fault7) / fails, 1) if fails else float(hours7),
            "MttrHours": round(hours7 * fault7 / fails, 1) if fails else 0.0,
            "DownMinutes": round(down_min, 0),
            "DownHours7d": round(hours7 * fault7, 2)}


def heartbeat(tok, last_state, now, payload):
    """Re-stamp each equipment State tag's held value at `now` when its last point is older than HEARTBEAT.

    The simulator writes a state tag only when the state changes, and Connect seeds a new Atlas subscription with
    the last hour only. After an Atlas restart, any unit whose state has held for over an hour (generators in
    standby for days, an ice cream machine in a long outage) reads blank until its next change. Writing the same
    value again changes nothing in the step-held state history (every metric here counts transitions), and keeps a
    point inside that hour for every tag.
    """
    missing = [n for n, p in last_state.items() if p is None]
    for i in range(0, len(missing), 40):
        data = read(tok, missing[i:i + 40], now - dt.timedelta(days=10), now)
        for n in missing[i:i + 40]:
            pts = data.get(n, [])
            last_state[n] = pts[-1] if pts else None
    stamped = 0
    for n, p in last_state.items():
        if p and now - p[0] > HEARTBEAT:
            payload.setdefault(n, []).append({"t": iso(now), "v": p[1], "q": 192})
            stamped += 1
    return stamped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=0, help="hours of history to write")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-baseline", action="store_true")
    a = ap.parse_args()

    now = dt.datetime.now(UTC).replace(microsecond=0)
    state = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            state = json.load(f)
    last_base = parse(state["last_baseline_utc"]) if state.get("last_baseline_utc") else None
    do_base = a.force_baseline or a.backfill > 0 or last_base is None or now - last_base > dt.timedelta(minutes=55)

    classes = psql("SELECT tag_segment, health_signal, array_to_string(steady_state_codes, ','), normal_value, normal_tolerance "
                   "FROM ref.equipment_class WHERE health_signal IS NOT NULL AND NOT is_deleted ORDER BY 1")
    stores = [r[0] for r in psql("SELECT store_id FROM org.store WHERE NOT is_deleted ORDER BY 1")]

    # time points to write
    avg_points = [now]
    base_points = [now] if do_base else []
    if a.backfill:
        start = now - dt.timedelta(hours=a.backfill)
        t = start.replace(minute=start.minute - start.minute % 5, second=0)
        avg_points = []
        while t <= now:
            avg_points.append(t); t += dt.timedelta(minutes=5)
        base_points = [t for t in avg_points if t.minute == 0] + [now]
    # Baselines need 3 days behind the earliest point; an Avg1h-only run looks back 12 h for the last steady hour.
    reach = dt.timedelta(days=BASELINE_DAYS) if base_points else dt.timedelta(hours=12)
    read_from = min(avg_points + base_points) - reach
    tok = token()
    payload, summary, last_state = {}, {}, {}
    for seg, sig, codes, normal, tol in classes:
        codes = {int(c) for c in codes.split(",")}
        normal, tol = float(normal), float(tol)
        modes = []
        for i in range(0, len(stores), BATCH):
            chunk = stores[i:i + BATCH]
            names = []
            for s in chunk:
                names += [f"{s}.{seg}.{sig}", f"{s}.{seg}.State"]
            data = read(tok, names, read_from, now)
            for s in chunk:
                signal, states = data.get(f"{s}.{seg}.{sig}", []), data.get(f"{s}.{seg}.State", [])
                last_state[f"{s}.{seg}.State"] = states[-1] if states else None
                steady = steady_samples(signal, states, codes)
                pre = f"{s}.{seg}.{sig}"
                for t in avg_points:
                    v = avg1h(steady, signal, t)
                    if v is not None:
                        payload.setdefault(pre + "Avg1h", []).append({"t": iso(t), "v": round(v, 3), "q": 192})
                for t in base_points:
                    m, sd, mode = baseline(steady, t, normal, tol)
                    payload.setdefault(pre + "BaselineMean", []).append({"t": iso(t), "v": round(m, 3), "q": 192})
                    payload.setdefault(pre + "BaselineStdDev", []).append({"t": iso(t), "v": round(sd, 3), "q": 192})
                    payload.setdefault(pre + "BaselineMode", []).append({"t": iso(t), "v": mode, "q": 192})
                    if t == base_points[-1]:
                        modes.append(mode)
        summary[seg] = {"self": sum(modes), "normal": len(modes) - sum(modes)} if modes else {}

    # Soft serve reliability: every run at `now`; with --backfill also hourly points (trend for Atlas history).
    ss_points = [now] if not a.backfill else [t for t in avg_points if t.minute == 0] + [now]
    ss_from = min(ss_points) - dt.timedelta(days=7, hours=1)
    grades = []
    for i in range(0, len(stores), 40):
        chunk = stores[i:i + 40]
        data = read(tok, [f"{s}.SoftServe.State" for s in chunk], ss_from, now)
        for s in chunk:
            states = data.get(f"{s}.SoftServe.State", [])
            last_state[f"{s}.SoftServe.State"] = states[-1] if states else None
            for t in ss_points:
                m = softserve_metrics(states, t)
                if m is None:
                    continue
                for k in SS_FIELDS:
                    payload.setdefault(f"{s}.SoftServe.{k}", []).append({"t": iso(t), "v": m[k], "q": 192})
                if t == now:
                    grades.append(m["Uptime7d"])
    summary["SoftServe"] = {"machines": len(grades), "uptime7d<90": sum(1 for g in grades if g < 90)}

    if not a.backfill:
        summary["heartbeat"] = heartbeat(tok, last_state, now, payload)

    points = sum(len(v) for v in payload.values())
    print(f"{iso(now)} tags={len(payload)} points={points} baseline={'yes' if base_points else 'no'} modes={summary}")
    if a.dry_run:
        return
    names = list(payload)
    for i in range(0, len(names), 200):
        r = curl(tok, "POST", HIST + "/data", json.dumps({n: payload[n] for n in names[i:i + 200]}))
        if not r or r.get("a", 0) < 1:
            print("write failed:", r, file=sys.stderr); sys.exit(1)
    if base_points:
        state["last_baseline_utc"] = iso(now)
    state["last_run_utc"] = iso(now)
    # Daily truck count (local calendar day). On the first run of a new day, recompile the Atlas domain so the
    # carriesPart edges and certification IsCurrent flags (compile-time statics) pick up the new day.
    today = str(dt.date.today())
    psql(f"CALL fleet.generate_inventory('{today}');")
    if state.get("last_inventory_date") != today:
        r = curl(tok, "PUT", ATLAS_WORLD)
        print(f"new day {today}: recompiled mcdonalds-ops -> {json.dumps(r)[:200]}")
        state["last_inventory_date"] = today
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


if __name__ == "__main__":
    main()
