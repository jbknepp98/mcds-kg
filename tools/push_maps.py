#!/usr/bin/env python3
"""Push atlas/maps.json to Atlas domain mcdonalds-ops over REST (Claude token -> draft session), then publish.
New definitions are added (creating their file if needed); existing ones are PATCHed in place."""
import json, os, subprocess, sys
TB = os.path.join(os.path.dirname(__file__), "tb.sh")
B = "https://localhost:4552/api/v1/branches/main"
D = B + "/domains/mcdonalds-ops"
def call(method, url, body=None):
    args = [TB, method, url] + ([json.dumps(body)] if body is not None else [])
    out = subprocess.run(args, capture_output=True, text=True).stdout
    text, _, code = out.rpartition("\nHTTP ")
    return int(code.strip()), (json.loads(text) if text.strip().startswith(("{", "[")) else text)
defs = json.load(open(os.path.join(os.path.dirname(__file__), "..", "atlas", "maps.json")))
code, files = call("GET", D + "/instance-maps")
stem = lambda n: n[:-len(".map.json")] if n.endswith(".map.json") else n
names = {stem(f["name"] if isinstance(f, dict) else f) + ".map.json" for f in (files if isinstance(files, list) else files.get("files", []))}
existing = {}
for fn in names:
    c, body = call("GET", f"{D}/instance-maps/{fn}/instances")
    for d in (body if isinstance(body, list) else body.get("definitions", body.get("instances", []))):
        existing[d["id"]] = fn
for d in defs:
    fn = d["fileName"]
    body = {k: v for k, v in d.items() if k != "fileName"}
    if d["id"] in existing:
        body = {k: v for k, v in body.items() if k != "id"}
        c, r = call("PATCH", f"{D}/instance-maps/instances/{d['id']}", body)
    else:
        if fn not in names:
            c, r = call("POST", D + "/instance-maps", {"name": stem(fn)}); print("create file", fn, c, "" if c < 300 else str(r)[:300])
            names.add(fn)
        c, r = call("POST", f"{D}/instance-maps/{fn}/instances", body)
    print(d["id"], c, "" if c < 300 else str(r)[:400])
    if c >= 300: sys.exit(1)
print(call("GET", B + "/draft"))
