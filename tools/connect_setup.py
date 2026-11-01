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
    }}}
hist = {"Settings": {
    "Host": "historian", "Port": 4512, "UseTls": True, "ClientName": "Timebase.Connect.McDonalds",
    "Auth": {"Mode": "Host"},
    "Datasets": {"McDonalds": {"Dataset": "McDonalds"}},
    "DefaultLookback": "01:00:00"}}
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
