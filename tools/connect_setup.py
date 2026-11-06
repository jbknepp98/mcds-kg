#!/usr/bin/env python3
"""Create/refresh the two Connect sources for McDonald's. Idempotent: matches on alias."""
import json, os, subprocess, sys
TB = os.path.join(os.path.dirname(__file__), "tb.sh")
BASE = "https://localhost:4562/api/connectors"
def call(method, url, body=None):
    args = [TB, method, url] + ([json.dumps(body)] if body is not None else [])
    out = subprocess.run(args, capture_output=True, text=True).stdout
    text, _, code = out.rpartition("\nHTTP ")
    code = int(code.strip())
    if code >= 300: sys.exit(f"{method} {url} -> {code}: {text[:800]}")
    return json.loads(text) if text.strip() else None
env = dict(l.strip().split("=", 1) for l in open(os.path.join(os.path.dirname(__file__), "..", "mcd.env")) if "=" in l)
ATLAS = "atl_7c3e18"
q = lambda sql: {"Sql": sql, "Subscription": {"NotSupported": True}}
pg = {"Settings": {
    "ConnectionString": f"Host=host.docker.internal;Port=5433;Database=mcdonalds_ar;Username=mcd_reader;Password={env['MCD_READER_PASSWORD']}",
    "CommandTimeout": "00:01:00",
    "Subscription": {"PollInterval": "01:00:00"},
    "Queries": {
        "Territories": q("SELECT territory_id, name, store_count FROM api.v_territory ORDER BY territory_id"),
        "Stores": q("SELECT * FROM api.v_store ORDER BY store_id"),
        "EquipmentClasses": q("SELECT * FROM api.v_equipment_class ORDER BY equipment_class_code"),
        "Certifications": q("SELECT * FROM api.v_certification ORDER BY certification_code"),
        "Parts": q("SELECT part_number, name, COALESCE(equipment_class_code, 'ANY') AS equipment_class_code, unit_cost_usd FROM api.v_part ORDER BY part_number"),
        "RepairTasks": q("SELECT * FROM api.v_repair_task ORDER BY repair_task_code"),
        "RepairTaskCertifications": q("SELECT * FROM api.v_repair_task_certification ORDER BY repair_task_certification_id"),
        "RepairTaskParts": q("SELECT * FROM api.v_repair_task_part ORDER BY repair_task_part_id"),
        "Technicians": q("SELECT technician_id, full_name, cert_level_code, level_rank, home_territory_id, home_store_id, to_char(hire_date, 'YYYY-MM-DD') AS hire_date, current_truck_id FROM api.v_technician ORDER BY technician_id"),
        "TechnicianCertifications": q("SELECT technician_id, certification_code, certificate_number, COALESCE(to_char(expires_date, 'YYYY-MM-DD'), 'never') AS expires_date, is_current FROM api.v_technician_certification_live ORDER BY technician_certification_id"),
        "Trucks": q("SELECT * FROM api.v_truck ORDER BY truck_id"),
        "TruckAssignments": q("SELECT truck_id, technician_id, to_char(start_date, 'YYYY-MM-DD') AS start_date FROM api.v_truck_assignment WHERE is_current ORDER BY truck_assignment_id"),
        "TruckInventory": q("SELECT truck_id, part_number, quantity_on_hand, par_quantity, to_char(inventory_date, 'YYYY-MM-DD') AS inventory_date FROM api.v_truck_inventory_current ORDER BY truck_part_id"),
        "StoreDistances": q("SELECT store_distance_id, from_store_id, to_store_id, road_miles, drive_minutes FROM api.v_store_distance ORDER BY store_distance_id"),
        # Live truck GPS (sql/13_routes.sql). Position, status and current store are served from each truck's 7-day
        # road trail as a time series (watermark on "Timestamp"), so Atlas UNWIND returns the route history; the next
        # stop has no history and is re-polled from the live view.
        **{f"Truck{sig}/[TruckId]": {
            "Sql": f'SELECT ts_utc AS "Timestamp", {col} AS "Value", \'Good\'::text AS "Quality" FROM api.v_truck_track_recent WHERE truck_id = @TruckId',
            "Parameters": {"TruckId": "string"},
            "Subscription": {"PollInterval": "00:01:00", "WatermarkColumn": "Timestamp"}}
           for sig, col in [("Latitude", "latitude"), ("Longitude", "longitude"), ("Status", "status_code::double precision"),
                            ("CurrentStore", "coalesce(store_id, \'\')")]},
        "TruckNextStore/[TruckId]": {
            "Sql": 'SELECT as_of_utc AS "Timestamp", coalesce(next_store_id, \'\') AS "Value", \'Good\'::text AS "Quality" FROM api.v_truck_position_live WHERE truck_id = @TruckId',
            "Parameters": {"TruckId": "string"},
            "Subscription": {"PollInterval": "00:01:00"}},
    }}}
hist = {"Settings": {
    "Host": "historian", "Port": 4512, "UseTls": True, "ClientName": "Timebase.Connect.McDonalds",
    "Auth": {"Mode": "Host"},
    "Datasets": {"McDonalds": {"Dataset": "McDonalds"}},
    "DefaultLookback": "01:00:00"}}   # 1 h seed after an Atlas restart; health_baseline.py heartbeats long-held state tags to stay inside it
CONTAINER, CFG = "timebase-2-0-beta-connect-1", "/connect/config/connector.config"


def apply_via_config_file(items):
    """Connect gc6 moved connector management to /app/connectors, which accepts only a signed-in browser session.
    Update the existing connectors in Connect's own config file instead: stop the container (so shutdown cannot
    rewrite the file), replace each connector's settings, start it again. Backs the old file up first."""
    import datetime, tempfile
    raw = subprocess.run(["docker", "exec", CONTAINER, "cat", CFG], capture_output=True, text=True, check=True).stdout
    bak = os.path.expanduser(f"~/timebase/backups/connect-connector.config.{datetime.datetime.now():%Y%m%d-%H%M%S}.bak")
    os.makedirs(os.path.dirname(bak), exist_ok=True)
    open(bak, "w").write(raw)
    cfg = json.loads(raw)
    by_alias = {c.get("alias"): cid for cid, c in cfg["connectors"].items()}
    for alias, _name, typ, settings in items:
        if alias not in by_alias:
            sys.exit(f"{alias} does not exist yet; create it once in the Connect UI ({typ}), then re-run")
        cfg["connectors"][by_alias[alias]]["config"] = settings["Settings"]
        cfg["connectors"][by_alias[alias]]["enabled"] = True
        print("updated", alias, by_alias[alias], "(config file)")
    with tempfile.NamedTemporaryFile("w", suffix=".config", delete=False) as f:
        json.dump(cfg, f, indent=2)
    os.chmod(f.name, 0o644)             # docker cp keeps the host owner and mode; Connect (uid 1654) must be able to read it
    subprocess.run(["docker", "stop", "-t", "30", CONTAINER], check=True, capture_output=True)
    subprocess.run(["docker", "cp", f.name, f"{CONTAINER}:{CFG}"], check=True)
    subprocess.run(["docker", "start", CONTAINER], check=True, capture_output=True)
    subprocess.run(["docker", "exec", "-u", "0", CONTAINER, "sh", "-c", f"chown 1654:1654 {CFG} && chmod 600 {CFG}"], check=True)
    os.unlink(f.name)
    print("Connect restarted; backup at", bak)


ITEMS = [("mcd-pg", "mcdonalds-postgres", "PGDG.PostgreSql", pg),
         ("mcd-historian", "mcdonalds-historian", "Timebase.Historian", hist)]
probe = subprocess.run([TB, "GET", BASE], capture_output=True, text=True).stdout
if probe.rstrip().endswith("HTTP 404"):
    apply_via_config_file(ITEMS)
    sys.exit(0)
existing = {c["alias"]: c for c in call("GET", BASE)}
for alias, name, typ, settings in ITEMS:
    if alias in existing:
        cid = existing[alias]["id"]
        call("PUT", f"{BASE}/{cid}/settings", settings)
        print("updated", alias, cid)
    else:
        c = call("POST", BASE, {"type": typ, "name": name, "alias": alias, "description": None,
                                "settings": settings, "atlases": [ATLAS]})
        cid = c["id"]; print("created", alias, cid)
    call("PATCH", f"{BASE}/{cid}/enabled", {"enabled": True})
