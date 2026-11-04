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
    }}}
hist = {"Settings": {
    "Host": "historian", "Port": 4512, "UseTls": True, "ClientName": "Timebase.Connect.McDonalds",
    "Auth": {"Mode": "Host"},
    "Datasets": {"McDonalds": {"Dataset": "McDonalds"}},
    "DefaultLookback": "01:00:00"}}   # 1 h seed after an Atlas restart; health_baseline.py heartbeats long-held state tags to stay inside it
existing = {c["alias"]: c for c in call("GET", BASE)}
for alias, name, typ, settings in [("mcd-pg", "mcdonalds-postgres", "PGDG.PostgreSql", pg),
                                   ("mcd-historian", "mcdonalds-historian", "Timebase.Historian", hist)]:
    if alias in existing:
        cid = existing[alias]["id"]
        call("PUT", f"{BASE}/{cid}/settings", settings)
        print("updated", alias, cid)
    else:
        c = call("POST", BASE, {"type": typ, "name": name, "alias": alias, "description": None,
                                "settings": settings, "atlases": [ATLAS]})
        cid = c["id"]; print("created", alias, cid)
    call("PATCH", f"{BASE}/{cid}/enabled", {"enabled": True})
