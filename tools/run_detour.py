#!/usr/bin/env python3
"""Run atlas/queries/detour_stops.cypher over Atlas REST and print a readable table.
Usage: run_detour.py TECH-003 AR-20031 AR-20039 [--rtr]"""
import json, os, subprocess, sys
args = [a for a in sys.argv[1:] if not a.startswith("--")]
tech, origin, dest = (args + ["TECH-001", "AR-20031", "AR-20039"][len(args):])[:3]
q = open(os.path.join(os.path.dirname(__file__), "..", "atlas", "queries", "detour_stops.cypher")).read()
tok = json.loads(subprocess.check_output([os.path.expanduser("~/.claude/timebase-local-headers.sh")]))["Authorization"]
body = json.dumps({"cypher": q, "parameters": {"tech": tech, "origin": origin, "dest": dest, "rightToRepair": "--rtr" in sys.argv}})
out = subprocess.run(["curl", "-sk", "-X", "POST", "-H", "Authorization: " + tok, "-H", "Content-Type: application/json", "--data-binary", "@-",
                      "https://localhost:4552/api/v1/branches/main/domains/mcdonalds-ops/queries"], input=body, capture_output=True, text=True).stdout
r = json.loads(out)
if "columns" not in r:
    sys.exit(out[:800])
rows = [dict(zip(r["columns"], x)) for x in r["data"]]
if not rows:
    sys.exit("no candidate stops on this route right now")
print(f"{rows[0]['techName']} ({rows[0]['truckId']})  {origin} -> {dest}  rightToRepair={'--rtr' in sys.argv}")
for x in rows:
    miss = ", ".join((["level"] if not x["levelOk"] else []) + (x["missingCerts"] or []) + (x["missingParts"] or []))
    hi = "fault" if x["hi"] is None else f"{x['hi']:.0f}"
    print(f"  {x['verdict']:<9} {x['store']} {x['city']:<18} {x['cls']:<9} idx {hi:>5}  +{x['detour']:>4} mi (allow {x['allowance']:>4})  ${x['usd'] or 0:>5,.0f}  {x['task']:<9} {('missing: ' + miss) if miss else ''}")
