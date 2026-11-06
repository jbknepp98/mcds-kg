#!/usr/bin/env python3
"""Keep simulator/mcdonalds.simulator.json in step with the running Timebase Data Collector (port 4522).

  tools/simulator_config.py export    copy the live "McDonalds" Simulator collector into the repo file
  tools/simulator_config.py diff      show whether the repo file and the live collector differ
  tools/simulator_config.py apply     write the repo file into the live collector (backup, stop, replace, start)

The gc6 Collector manages collectors only through a signed-in browser session, so, like tools/connect_setup.py, this
works on the Collector's own config file (/collector/config/collectors.config). `apply` keeps the collector's id and
its Historian link, and only creates the collector if none named "McDonalds" exists yet (it then needs the Historian
id: --historian hst_xxxxxx, from the Collector UI). Changing the sequences of a dataset that already holds data
mixes old and new history; see simulator/README.md before applying a changed config.
"""
import datetime, json, os, subprocess, sys, tempfile

CONTAINER = "timebase-2-0-beta-collector-1"
CFG = "/collector/config/collectors.config"
NAME = "McDonalds"
REPO = os.path.join(os.path.dirname(__file__), "..", "simulator", "mcdonalds.simulator.json")


def live():
    raw = subprocess.run(["docker", "exec", CONTAINER, "cat", CFG], capture_output=True, text=True, check=True).stdout
    return raw, json.loads(raw)


def find(cfg):
    return next(((cid, c) for cid, c in cfg["collectors"].items() if c.get("name") == NAME and c.get("type") == "Simulator"),
                (None, None))


def repo_view(c):
    return {"name": c["name"], "type": c["type"], "description": c.get("description"), "config": c["config"]}


cmd = sys.argv[1] if len(sys.argv) > 1 else ""
raw, cfg = live()
cid, col = find(cfg)

if cmd == "export":
    if not col:
        sys.exit(f'no Simulator collector named "{NAME}" in {CONTAINER}')
    with open(REPO, "w") as f:
        json.dump(repo_view(col), f, indent=2, ensure_ascii=False); f.write("\n")
    seqs = col["config"]["Sequences"]
    print(f"exported {cid}: {len(seqs)} sequences -> simulator/mcdonalds.simulator.json")

elif cmd == "diff":
    want = json.load(open(REPO))
    print("same" if col and repo_view(col) == want else "DIFFERENT (or missing)")

elif cmd == "apply":
    want = json.load(open(REPO))
    if col and repo_view(col) == want:
        sys.exit("live collector already matches the repo file; nothing to do")
    bak = os.path.expanduser(f"~/timebase/backups/collector-collectors.config.{datetime.datetime.now():%Y%m%d-%H%M%S}.bak")
    os.makedirs(os.path.dirname(bak), exist_ok=True)
    open(bak, "w").write(raw)
    if col:
        col.update({"description": want["description"], "config": want["config"], "enabled": True})
    else:
        if "--historian" not in sys.argv:
            sys.exit("no McDonalds collector yet: pass --historian <hst_id> (Collector UI > Historians)")
        hst = sys.argv[sys.argv.index("--historian") + 1]
        cid = "col_" + os.urandom(3).hex()
        cfg["collectors"][cid] = {**want, "enabled": True, "historians": [{"id": hst, "dataset": "McDonalds"}]}
    with tempfile.NamedTemporaryFile("w", suffix=".config", delete=False) as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.chmod(f.name, 0o644)   # docker cp keeps the host mode; the Collector (uid 1654) must be able to read it
    subprocess.run(["docker", "stop", "-t", "30", CONTAINER], check=True, capture_output=True)
    subprocess.run(["docker", "cp", f.name, f"{CONTAINER}:{CFG}"], check=True)
    subprocess.run(["docker", "start", CONTAINER], check=True, capture_output=True)
    subprocess.run(["docker", "exec", "-u", "0", CONTAINER, "sh", "-c", f"chown 1654:1654 {CFG} && chmod 600 {CFG}"], check=True)
    os.unlink(f.name)
    print(f"applied to {cid}; Collector restarted; backup at {bak}")

else:
    sys.exit(__doc__)
