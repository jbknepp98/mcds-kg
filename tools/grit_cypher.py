#!/usr/bin/env python3
"""Run a Cypher query on grit Atlas over MCP; print the raw text result."""
import json, subprocess, sys, urllib.request, re
U = "https://grit.timebase.cloud:4552/mcp"
H = json.loads(subprocess.check_output([f"{__import__('os').path.expanduser('~')}/.claude/grit-headers.sh"]))
def post(body, sid=None):
    h = {**H, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if sid: h["Mcp-Session-Id"] = sid
    r = urllib.request.urlopen(urllib.request.Request(U, json.dumps(body).encode(), h), timeout=120)
    t = r.read().decode(); m = re.search(r"data: (.*)", t)
    return r.headers.get("Mcp-Session-Id"), (json.loads(m.group(1)) if m else (json.loads(t) if t.strip() else None))
sid, _ = post({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"mcd","version":"1"}}})
post({"jsonrpc":"2.0","method":"notifications/initialized"}, sid)
_, res = post({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":sys.argv[1],"arguments":json.loads(sys.argv[2])}}, sid)
if "error" in res: sys.exit(json.dumps(res["error"]))
print("".join(c.get("text","") for c in res["result"]["content"]))
