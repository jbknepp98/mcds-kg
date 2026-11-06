# Setup

How to run the demo, and how to stand it up on another machine.

> **Status:** the demo runs on Jeff's Mac. The steps for a new machine are written from how it was built and haven't
> yet been run end to end on a clean one. Expect to adjust names and IDs on the way.

## What you need

| Requirement | Notes |
|---|---|
| Docker | Everything runs in containers. |
| Timebase 2.0 stack (gc6 or later) | Pulse, Historian, Collector, Connect, Atlas (Explorer and Bridge optional), each with its default port: Historian 4512, Collector 4522, Atlas 4552, Connect 4562. |
| A Pulse client for scripts | The tools authenticate with a bearer token. They get it from `~/.claude/timebase-local-headers.sh`, which must print `{"Authorization": "Bearer …"}`. Any script that does that works. |
| PostgreSQL 16 in Docker | Here it's the container `bible-pg` on host port 5433, shared with another project. Connect reaches it at `host.docker.internal:5433`. |
| Python 3.9+ | Standard library only; no pip installs. |
| `mcd.env` in the repo root | Not in git. Holds `MCD_ADMIN_PASSWORD` and `MCD_READER_PASSWORD`. Create it yourself. |
| Only to re-plan the van routes | The `~/arkansas-routing` Valhalla tiles (OpenStreetMap Arkansas). Not needed to run the demo; the plan is committed. |

### Machine-specific names to change on another machine

| Name | Where it's used |
|---|---|
| Postgres container `bible-pg`, admin role `bible_admin`, port 5433 | `build.sh`, `sql/00_database.sh`, `tools/connect_setup.py`, `dashboard/server.py`, `tools/health_baseline.py` |
| Connect container `timebase-2-0-beta-connect-1` | `tools/connect_setup.py` |
| Collector container `timebase-2-0-beta-collector-1` | `tools/simulator_config.py` |
| Atlas id `atl_7c3e18` | `tools/connect_setup.py` |
| Connector ids `con_c10edc` (Postgres) and `con_faabed` (Historian) | `atlas/domain/instances/*.map.json`, `tools/gen_maps.py` |
| launchd labels `com.jeff.mcdonalds-*` and paths in `launchd/*.plist` | the two background jobs (macOS) |

## Running it day to day

Two background jobs keep it going (macOS launchd):

| Job | Does | Logs |
|---|---|---|
| `com.jeff.mcdonalds-health-baseline` | Runs `tools/health_baseline.py` every 5 minutes: averages, baselines, ice cream uptime, daily van inventory, daily Atlas recompile | `logs/health_baseline.*` |
| `com.jeff.mcdonalds-softserve-finder` | Runs the dashboard, `dashboard/server.py`, on http://127.0.0.1:8787 | `logs/` |

Install them once: `cp launchd/*.plist ~/Library/LaunchAgents/`, then `launchctl load ~/Library/LaunchAgents/com.jeff.mcdonalds-*.plist`.

### Before a demo

1. The Timebase stack is up (`docker ps`), and the Collector's **McDonalds** simulator shows *Running*.
2. The dashboard loads at http://127.0.0.1:8787 and the three tabs show numbers.
3. The health job ran recently: `tail -3 logs/health_baseline.log`.
4. If Atlas was restarted, give it about 6 minutes to recompile and reconnect before the live values fill in.
5. If the Mac was asleep, the health job catches up on its next run; health values may lag for a few minutes.

## Building on a new machine

Do the steps in order. Each one is safe to re-run.

### 1. Historian dataset and the equipment simulator

1. In the Historian, create the dataset **McDonalds**.
2. Create the simulator: paste the `config` object from `simulator/mcdonalds.simulator.json` into a new **Simulator**
   collector in the Collector UI writing to that dataset, or run
   `tools/simulator_config.py apply --historian <historian id>`.
3. The collector backfills 7 days, then runs live. Details: [`simulator/README.md`](../simulator/README.md).

### 2. Postgres

```bash
./build.sh
```

Creates the roles and the `mcdonalds_ar` database, loads everything in `sql/` in order, and finishes with 67 checks
(20 + 47). **Every row must say PASS.**

### 3. Connect

1. In the Connect UI, create two connectors once: **mcd-pg** (PostgreSQL) and **mcd-historian** (Timebase
   Historian), both attached to your Atlas.
2. `tools/connect_setup.py` fills in their settings: the 14 Postgres topics, the 5 per-van GPS templates and the
   Historian dataset. On gc6 it does this by editing Connect's config file and restarting Connect (backup in
   `~/timebase/backups/`).

### 4. Atlas

1. Import the library from `atlas/library/mcdonalds.jsonld` (it depends only on `atlas-common`).
2. Create the domain `mcdonalds-ops`, importing `mcdonalds`.
3. Update the connector ids in `atlas/domain/instances/*.map.json` and `tools/gen_maps.py` to your own.
4. `tools/gen_maps.py`, then `tools/push_maps.py` to load the instance maps.
5. Compile: `tools/tb.sh PUT https://localhost:4552/api/v1/branches/main/domains/mcdonalds-ops/world`.
6. Check the counts against "Expected compiled counts" in [REFERENCE.md](REFERENCE.md): 1,221 instances.
7. Optional, for Gage: copy `atlas/skills/mcdonalds-ops-queries/` into `/atlas/config/skills/` in the Atlas container
   and restart Atlas.

### 5. Health job and dashboard

1. One-off history so the health index has something to work with: `tools/health_baseline.py --backfill 24`
   (about 8 minutes).
2. Install the two launchd jobs (above), or run `python3 dashboard/server.py` by hand.
3. The Store Monitor loads 7 days of history on first start (about 35 seconds; the page shows progress).

### 6. Optional: re-plan the van routes

Only if stores, technicians or the rotation change:

```bash
tools/valhalla.sh up        # routing server on :8002 from the OpenStreetMap Arkansas tiles
tools/plan_routes.py        # regenerates sql/13_routes_data.sql and loads it
tools/valhalla.sh down
```

The plan is seeded per technician and day, so re-running it on the same stores and roads changes nothing.

## Repo layout

| Folder | Contents |
|---|---|
| `sql/` | Numbered, re-runnable build scripts, run in order by `build.sh`, plus `verify_*.sql` |
| `simulator/` | The Data Collector simulator config and its explanation |
| `atlas/` | Copies of the Atlas library, domain and instance maps; demo queries; the Gage skill |
| `dashboard/` | The local web dashboard (`server.py`, `index.html`, `monitor.js`, `fleet.js`) |
| `tools/` | Setup and maintenance scripts: Connect, simulator, Atlas maps, health job, route planner |
| `launchd/` | macOS background job definitions |
| `seed/` | Source data for the store list (from grit) and ZIP centroids (Census) |
| `docs/` | These documents |
