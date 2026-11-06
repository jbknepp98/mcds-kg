# Equipment data: the Historian simulator

There are no real sensors in this demo. Every equipment reading (cooler and freezer temperatures, HVAC supply air,
generator load, ice cream machine state) comes from the **Timebase Data Collector's Simulator plugin**, which writes
live tag data into the Historian dataset `McDonalds` around the clock. Everything downstream (the health job, Atlas,
the dashboards) reads those tags as if they came from a real store's controllers.

`mcdonalds.simulator.json` is the exact configuration of that collector, exported from the running Collector.

| | |
|---|---|
| Collector | Timebase Data Collector, https://localhost:4522, collector **McDonalds** (`col_ed5672` locally), plugin **Simulator** |
| Writes to | Historian dataset **McDonalds** |
| Tags | **1,719**: 191 stores × (Cooler 2 + Freezer 2 + HVAC 2 + Generator 2 + Soft serve 1) |
| Tag names | `AR-<store number>.<Asset>.<Signal>`, e.g. `AR-20031.Cooler.Temperature`, `AR-20031.SoftServe.State` |
| Backfill | 7 days of history is generated when the collector first starts, so the dashboards have a week to show |
| State | the simulator remembers where each unit is in its cycle in `/state` inside the Collector, so a restart resumes rather than starts over |

## How it is put together

The Simulator runs **sequences**. A sequence is a loop of steps (Off Cycle → Cooling → Holding → Door Open → … →
Defrost), each lasting a random number of minutes, and it runs one copy of that loop for every store in its list.
Each step sets the `.State` tag to that step's code, and the measurement tag ramps to a target value with noise.

Each equipment class has **two sequences**, and every store is in exactly one of them. That split is what gives the
demo its story: most stores are fine, and a minority have equipment that is quietly going bad.

| Sequence | Stores | Loop length | Faults | What it looks like |
|---|---:|---|---|---|
| `Coolers_Healthy` | 153 | ~5 days | 1 per loop, 20 min–3 h | Holds about 38 °F |
| `Coolers_AtRisk` | 38 | ~1.4 days | 1 per loop, 1–4 h | Holds about 40.5 °F, runs warm all the time |
| `Freezers_Healthy` | 153 | ~5 days | 1 per loop, 20 min–3 h | Holds about −4 °F |
| `Freezers_AtRisk` | 38 | ~1.5 days | 1 per loop, 2–6 h | Holds about +1 °F |
| `HVACUnits_Healthy` | 153 | ~5 days | 1 per loop, 30 min–4 h | Supply air about 57 °F while cooling |
| `HVACUnits_AtRisk` | 38 | ~2 days | 1 per loop, 3–10 h | Supply air about 64 °F, struggling |
| `Generators_Healthy` | 153 | weekly exercise run | power outage run about every 7 months | 70 % ± 15 load when running |
| `Generators_AtRisk` | 38 | weekly exercise run | power outage run about every 7 weeks | 85 % ± 14 load, working too hard |
| `SoftServe_Reliable` | 96 | ~10 days | 1 per loop, 1–4 h | One "Needs Service" about every 10 days |
| `SoftServe_Unreliable` | 95 | ~2.6 days | 1 per loop, 8–24 h | Broken a quarter of the time |

The at-risk store lists differ per class, so a store can have an at-risk cooler and a healthy HVAC unit.

**Why at-risk units matter for the health index.** An at-risk unit has always run warm, so compared only with its
own history it looks normal. The health job therefore also scores each unit against the *design* normal stored in
`ref.equipment_class` (see "Health index" in the main README). That is the point of the demo: Timebase spots the
units that are drifting before they fault.

## State codes

The `.State` tags carry these codes (the same codes are enum types in the Atlas `mcdonalds` library):

| Asset | Codes |
|---|---|
| Cooler, Freezer | 0 Off Cycle, 10 Cooling, 20 Holding, 21 Door Open, 22 Stocking, 30 Defrost, 40 Fault – Door/Seal, 41 Fault – Compressor, 42 Fault – Temperature Sensor, 43 Fault – Evaporator Fan |
| HVAC | 0 Off – Unoccupied, 10 Startup, 20 Cooling – Occupied, 21 Economizer, 22 Fan Only, 30 Setback, 40 Fault – Airflow/Filter, 41 Fault – Compressor/Condenser, 42 Fault – Thermostat/Sensor |
| Generator | 0 Standby, 10 Exercise Run – Scheduled, 30 Unplanned Run – Possible Power Outage |
| Soft serve | 0 Operational, 10 Heat Treat Cycle, 20 Mix Low, 40 Fault – Needs Service |

A code of 40 or above means the store already knows something is wrong (service condition 3 in Atlas).

## Things to know

- **The sequences are independent.** Each store's loop runs on its own clock. Nothing links a cooler fault to an HVAC
  fault at the same store, and a power outage at one store does not affect its neighbours.
- **State tags only change on transitions.** A generator in standby writes nothing for days. The health job
  re-stamps long-held states so Atlas never reads them as blank (see "State heartbeat" in the main README).
- **A Collector restart sends every unit back to the first step of its loop** (seen on 2.0-gc6 and 2.0.0; the saved
  state keeps the timeline but not the position in the loop). Because each loop ends with its fault step, nothing
  faults for a while after a restart: about a day for at-risk coolers, freezers and HVAC, 2 days for unreliable ice
  cream machines, up to 5 days for healthy units. Drifting (Warning/Danger) units still show, because they are
  about temperatures, not faults. Avoid restarting the Collector shortly before a demo.
- **The store lists are hard-coded** in each sequence's `map`. They must match `org.store` in Postgres. If stores are
  added or removed, update the lists so every store number appears in exactly one sequence per class.

## Keeping the repo copy and the Collector in step

```bash
tools/simulator_config.py diff      # does the live collector match simulator/mcdonalds.simulator.json?
tools/simulator_config.py export    # live collector -> repo file (after changing it in the Collector UI)
tools/simulator_config.py apply     # repo file -> live collector (backs up, stops, replaces, starts the Collector)
```

The gc6 Collector only accepts collector changes from a signed-in browser session, so the tool edits the Collector's
own `collectors.config` instead, the same way `tools/connect_setup.py` handles Connect. The backup goes to
`~/timebase/backups/`.

**On a new machine:** create the Historian dataset `McDonalds`, then either paste the `config` object from
`mcdonalds.simulator.json` into a new Simulator collector in the Collector UI, or run
`tools/simulator_config.py apply --historian <historian id>`.

**Changing a config that is already running.** The new sequences carry on from the old history, so the change is
visible as a break in the data. For a clean slate: stop the collector, clear the `McDonalds` dataset in the Historian,
delete the simulator's saved state, then start it again. The 7-day backfill then rebuilds a consistent week.
