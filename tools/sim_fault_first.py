#!/usr/bin/env python3
"""Restructure simulator/mcdonalds.simulator.json so faults come back soon after a Collector restart.

Why: a Collector restart sends every simulated unit back to step 1 of its loop, and each loop ended with its fault
step, so after a restart nothing faulted for 1-5 days and all units ran in lockstep.

What it does, per sequence (fault frequency is kept):
  old loop:  S (normal steps, mean length T)  + FAULT
  new loop:  LEAD + FAULT + S'
    LEAD  = the steady state (Holding / Cooling - Occupied / Standby / Operational), lasting random(1, L) minutes,
            L = T, capped at 24 h for coolers, freezers and HVAC so their defrost and day/night cycles stay visible
    S'    = the first steps of S, cut at the step boundary closest to T - L/2, so the loop's mean length is unchanged
After a restart each unit spends a random time in its steady state and then faults, so faults are spread out from
the first minutes instead of all arriving days later.

Idempotent: a sequence whose second step is already its fault is left alone.
  tools/sim_fault_first.py           rewrite the repo file (then: tools/simulator_config.py apply)
  tools/sim_fault_first.py --check   print what would change
"""
import json, os, re, sys

REPO = os.path.join(os.path.dirname(__file__), "..", "simulator", "mcdonalds.simulator.json")
STEADY = {"Coolers": "20", "Freezers": "20", "HVACUnits": "20", "Generators": "0", "SoftServe": "0"}
CAP_MIN = {"Coolers": 1440, "Freezers": 1440, "HVACUnits": 1440}


def mean(d):
    m = re.match(r"random\(([\d.]+),\s*([\d.]+)\)", str(d))
    return (float(m[1]) + float(m[2])) / 2 if m else float(d)


def is_fault(cls, step):
    v = str(step["value"])
    return v.startswith("random(4") or v == "40" or (cls == "Generators" and v == "30")


doc = json.load(open(REPO))
changed = []
for name, seq in doc["config"]["Sequences"].items():
    cls = name.split("_")[0]
    steps = seq["steps"]
    if len(steps) > 1 and is_fault(cls, steps[1]) and not is_fault(cls, steps[-1]):
        continue                                        # already restructured
    assert is_fault(cls, steps[-1]) and not any(is_fault(cls, s) for s in steps[:-1]), name
    normal, fault = steps[:-1], steps[-1]
    T = sum(mean(s["duration"]) for s in normal)
    L = min(T, CAP_MIN.get(cls, T))
    sums = [0.0]                                        # cut at the step boundary closest to T - L/2
    for s in normal:
        sums.append(sums[-1] + mean(s["duration"]))
    keep = min(range(1, len(sums)), key=lambda k: abs(sums[k] - (T - L / 2)))
    acc = sums[keep]
    steady_i = next(i for i, s in enumerate(normal) if str(s["value"]) == STEADY[cls])
    lead = {"value": STEADY[cls], "duration": f"random(1, {round(L)})"}
    seq["steps"] = [lead, fault] + normal[:keep]
    for tag in seq["tags"]:
        v = tag["values"]
        if len(v) == len(steps):                        # step-indexed values; a 1-entry ["step"] tag stays as is
            tag["values"] = [v[steady_i], v[-1]] + v[:keep]
    new_mean = L / 2 + mean(fault["duration"]) + acc
    changed.append(f"{name:22} lead up to {L/60:6.1f} h, kept {keep}/{len(normal)} normal steps, "
                   f"loop {(T + mean(fault['duration']))/60:7.1f} h -> {new_mean/60:7.1f} h")

print("\n".join(changed) or "nothing to change")
if changed and "--check" not in sys.argv:
    with open(REPO, "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False); f.write("\n")
    print("wrote simulator/mcdonalds.simulator.json; apply with tools/simulator_config.py apply")
