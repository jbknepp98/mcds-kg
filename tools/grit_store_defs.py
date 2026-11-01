#!/usr/bin/env python3
"""Fetch every StoreAsset definition from grit and merge exact static values into seed/stores_grit.csv."""
import csv, json, re, subprocess, concurrent.futures as cf
rows = list(csv.DictReader(open("seed/stores_grit.csv")))
P = {"StoreId":"store_id","RestaurantName":"restaurant_name","Address":"address","City":"city","State":"state","Zip":"zip",
     "County":"county","Latitude":"latitude","Longitude":"longitude","Phone":"phone","OperatingStatus":"operating_status",
     "RestaurantHours":"restaurant_hours","DriveThruHours":"drive_thru_hours","Is24Hour":"is_24_hour","HasDriveThru":"has_drive_thru",
     "HasMobileOrdering":"has_mobile_ordering","HasDelivery":"has_delivery","HasKiosk":"has_kiosk","HasPlayPlace":"has_play_place",
     "LocationType":"location_type"}
def fetch(sid):
    t = json.loads(subprocess.check_output(["python3","tools/grit_cypher.py","GetInstanceMapDefinition",
          json.dumps({"domain":"mcdowells-ops","id":sid})]).decode())
    d = {"label": re.search(r"Instance Label: (.*)", t).group(1)}
    for prop, val in re.findall(r"mcdowells-ops:(\w+):\n    static value=(.*)", t):
        d[P[prop]] = val
    return sid, d, t
diffs = []
with cf.ThreadPoolExecutor(8) as ex:
    res = dict((s, (d, t)) for s, d, t in ex.map(fetch, [r["store_id"] for r in rows]))
open("seed/grit_store_definitions.txt","w").write("\n\n".join(res[k][1] for k in sorted(res)))
for r in rows:
    d = res[r["store_id"]][0]
    for k, v in d.items():
        old = r[k]
        if k.startswith(("is_","has_")): v = v.lower()
        if old != v: diffs.append((r["store_id"], k, old, v))
        r[k] = v
    for k in P.values():
        if k not in d and k != "store_id": r[k] = ""; diffs.append((r["store_id"], k, "(absent in def)", ""))
with open("seed/stores_grit.csv","w",newline="") as f:
    w = csv.DictWriter(f, rows[0].keys()); w.writeheader(); w.writerows(rows)
from collections import Counter
print(len(res), "definitions;", Counter(k for _, k, _, _ in diffs))
for x in diffs[:15]: print(x)
