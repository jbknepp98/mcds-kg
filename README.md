# McDonald's Arkansas — demo data + Atlas domain

Rebuilt locally from grit's `mcdowells-ops` (store/territory layer), branded McDonald's, then extended with a
field-service layer: technicians, certifications, trucks, daily truck parts inventory, a live equipment health
matrix and consequence-weighted detour stops.

| Piece | Where |
|---|---|
| Equipment data | Timebase Data Collector (https://localhost:4522), Simulator collector `McDonalds`: 1,719 live tags for 191 stores × 5 equipment types into Historian dataset `McDonalds`, with a healthy and an at-risk population per type. Config in `simulator/mcdonalds.simulator.json`, explained in [`simulator/README.md`](simulator/README.md); sync with `tools/simulator_config.py diff\|export\|apply` |
| Postgres DB | `mcdonalds_ar` in container `bible-pg` (localhost:5433). Owner `mcd_admin`, read-only `mcd_reader` (api views only). Passwords in `mcd.env` (gitignored) |
| Schemas | `util` (audit plumbing), `ref` (vocabularies, equipment health/consequence settings, certifications, parts, repair tasks), `org` (territory, store), `hr` (technician, technician_certification), `fleet` (truck, truck_assignment, truck_par_level, truck_inventory_daily, route_setting, route_stop, route_leg), `geo` (store_distance), `api` (views Connect polls) |
| Connect | `mcd-pg` = `con_c10edc` (14 topics: Territories, Stores, EquipmentClasses, Certifications, Parts, RepairTasks, RepairTaskCertifications, RepairTaskParts, Technicians, TechnicianCertifications, Trucks, TruckAssignments, TruckInventory, StoreDistances, plus 5 per-truck GPS templates `Truck{Latitude,Longitude,Status,CurrentStore,NextStore}/[TruckId]` polled every minute); `mcd-historian` = `con_faabed` (dataset `McDonalds`, template `con_faabed/McDonalds/[Tag]`) |
| Health job | `tools/health_baseline.py`, every 5 min via launchd `com.jeff.mcdonalds-health-baseline` (`launchd/`, logs in `logs/`) |
| Atlas | library `mcdonalds` (only dependency: atlas-common), domain `mcdonalds-ops`; copies in `atlas/`; demo queries in `atlas/queries/` (`tools/run_detour.py TECH-003 AR-20031 AR-20039 [--rtr]`) |
| Soft Serve Finder | `dashboard/` — http://127.0.0.1:8787 (launchd `com.jeff.mcdonalds-softserve-finder`). URL params `?zip=72032&rtr=1` |
| Van GPS | Technicians drive real Arkansas roads during the day; see **Technician vans on the road** below. Finder map: van layer + "Show today's route" |
| Fleet Tracker | Third tab, http://127.0.0.1:8787/#fleet. All 18 vans on a statewide map with who's driving, live status, ETA, certifications and today's route (stops + road trail from Atlas history); all 191 stores coloured by their worst live equipment condition, each with its nearest vans and whether they're certified for the problem. KPI: faults with an on-duty certified van within 30 mi. Below the map, a certification matrix (18 technicians × 5 certifications, grouped by territory): current / expiring within 90 days / expired / not held, holders per territory with gaps flagged, certificate numbers and the repair tasks each unlocks on hover; from Atlas `holdsCertification` edges. Links `#fleet?terr=Central%20Arkansas&status=10&van=TRK-101`. Code in `dashboard/fleet.js`; endpoint `/api/fleet` (vans, drivers, GPS, territories, certs from Atlas; today's plan and ETAs from Postgres; store conditions from the Monitor's Atlas reads) |
| Store Monitor | Second tab, http://127.0.0.1:8787/#monitor. Watch one store, a territory, your own fleet (saved in the browser) or all stores; live values from Atlas, 6 h–7 days of history from the Historian. Link format `#monitor?scope=store&store=AR-20031&h=72&eq=COOLER,HVAC&focus=AR-20031.HVAC&cmp=AR-20012`. Code in `dashboard/monitor.js`; endpoints `/api/monitor/*` in `server.py` |

## Rebuild
- Equipment simulator: `tools/simulator_config.py diff` (repo vs live Collector), `export`, or `apply` (writes the repo config into the Collector; see `simulator/README.md`)
- DB: `./build.sh` (idempotent; ends with `sql/verify_org.sql` (20 checks) and `sql/verify_service.sql` (47 checks), all rows must say PASS)
- Seed refresh from grit: `tools/grit_cypher.py` export → `seed/stores_grit.csv`, then `tools/grit_store_defs.py` (exact coords from definitions), `tools/gen_org_data.py`
- Connect sources: `tools/connect_setup.py` (matches on alias). On gc6 the connector API moved to `/app/connectors`, which only accepts a signed-in browser session, so the tool writes Connect's own `/connect/config/connector.config` instead: backup to `~/timebase/backups/`, stop the container, replace the two connectors' settings, start it, restore owner uid 1654 + mode 600 (Connect refuses to start if it cannot read the file). Creating a brand-new connector still needs the UI once
- Atlas maps: `tools/gen_maps.py` → `atlas/maps.json` (reads class settings from `ref.equipment_class`), then `tools/push_maps.py` (REST, Claude token; adds or PATCHes each definition, publishes the draft if one opens). Recompile: `PUT /api/v1/branches/main/domains/mcdonalds-ops/world`
- Store Monitor history: on start the server loads 7 days of State/Avg1h/baseline tags for all 955 units (~35 s; the page shows progress), then reads only new data every 60 s. Health history is recomputed with the Atlas `HealthIndexOf` formula from the Avg1h/baseline tags, so it starts when the health job did (2026-11-01). Value-less quality-64 points on State tags are treated as "state unchanged"; other value-less points (the Historian shutdown marker, quality 28) show as No data.
- Health job + dashboard: `cp launchd/*.plist ~/Library/LaunchAgents/` then `launchctl load` each. One-off history: `tools/health_baseline.py --backfill 24` (~8 min)
- ZIP centroids: `seed/ar_zcta_2023.csv` (Census 2023 ZCTA Gazetteer, AR prefixes 716-729) → `sql/10_geo_zip_data.sql`

## Health index (the "health matrix")
Atlas functions only see a point in time, and the Historian has no aggregation, so `health_baseline.py` computes the
windowed inputs and writes them back to the Historian; Atlas binds them and does the scoring.

- **Steady state only.** Baseline and averages use only the class's `steady_state_codes` (Holding for coolers/freezers, Cooling-Occupied for HVAC, running for generators) so defrost, door-open and fault periods don't count.
- **Per unit, per signal** the job writes `<Store>.<Class>.<Signal>Avg1h` (every 5 min: last hour of steady operation), `…BaselineMean`, `…BaselineStdDev`, `…BaselineMode` (hourly).
- **Baseline:** the unit's own 3-day hourly means if it has ≥24 steady hours with real variation (`BaselineMode` 1); otherwise defined normal operation from `ref.equipment_class` (`BaselineMode` 0). Coolers, freezers and HVAC all use their own baseline; generators sit in standby for days and fall back to normal (70 ± 6 % load when running).
- **Atlas `HealthIndexOf`:** z = worse of (avg − own mean)/own sd and (avg − design normal)/tolerance; index = 100 − 25 × (z − 1), clamped 0–100. 70+ Healthy, 40–70 Warning, < 40 Danger. The design check matters: the simulator's at-risk units have always run hot, so against their own history they look normal.
- **`ServiceConditionOf`:** 0 Healthy, 1 Warning undetected, 2 Danger undetected, 3 Fault detected (state code ≥ 40 — the store already knows).
- **`DetourAllowanceMilesOf`:** max detour by consequence × urgency (0 at index 100 → 1 at 40). Freezer 40 mi ($6,000 of frozen product), cooler 30, HVAC 15, soft serve 10 (faults only, for fun), generator 5. `ExposureUsdOf` is the same urgency × product at risk.
- **State heartbeat:** the simulator writes a `.State` tag only when the state changes, and Connect seeds a new
  Atlas subscription with just the last hour. So after an Atlas restart, a unit that had held its state longer
  (generators in standby for days, an ice cream machine in a long outage) read blank. Each run, the job re-stamps
  the held value of any state tag older than 40 min. That's harmless, because every metric counts transitions,
  not points. Raising the connector's `DefaultLookback` does not help (tested: subscriptions ignore it).
- Matrix view: `atlas/queries/health_matrix.cypher`. `Store.StoreHealthIndex` = worst unit (via `WorstHealthIndex`).

## Detour stops (the demo)
`atlas/queries/detour_stops.cypher` with `$tech`, `$origin`, `$dest`. Rows = drifting units (condition 1/2) at open
stores whose extra driving (origin→store→dest − origin→dest, from `roadDistanceTo` edges) is within that unit's
`DetourAllowanceMiles`, joined to the repair task for its class and condition. `STOP` = technician level ≥ task
minimum, every required certification held and current, every required part on today's truck count; otherwise
`NEAR MISS` with what is missing. Suggested route: Little Rock AR-20031 → West Memphis AR-20039 (I-40, 167 road mi),
TECH-001 Darnell Brooks (Senior, full truck) vs TECH-003 Cody Whitfield (Apprentice; no EPA 608, carries no cooler gasket).

Seeded storylines: TECH-002 Priya Raman's Generac certification lapsed 2026-09-15 at the anchor, 47 days before (she still carries generator parts); TECH-003 Cody Whitfield isn't Taylor-certified (the Right to Repair hero);
TRK-103 was Darnell's van until June 2025; TRK-101 is out of R-410A on 2026-11-01.

Certification dates roll with the calendar. The seed dates are written against the demo anchor in `ref.demo_setting`
(2026-11-01); `api.v_technician_certification_live` shifts issue and expiry dates by `current_date - anchor_date` and
exposes `days_to_expiry`, so the story is the same on any day: Priya's GEN is always 47 days lapsed, Curtis Webb's REFRIG
always has 5 days left. Stored rows never change. The health job recompiles the Atlas domain on its first run each day,
which is how Atlas picks up the shifted dates.

## The ice cream machine (soft serve)
- The simulator already splits machines into `SoftServe_Reliable` (96 stores, one fault about every 10 days) and `SoftServe_Unreliable` (95 stores, 2-3 faults a week, 8-24 h each).
- `health_baseline.py` derives, per machine, from 7 days of `SoftServe.State`: `Uptime24h`, `Uptime7d` (% not in Needs Service), `Serving7d` (% actually serving), `Failures7d`, `MtbfHours`, `MttrHours`, `DownMinutes` (current outage), `DownHours7d`.
- Atlas: `ReliabilityScoreOf` = 70% × Uptime7d + 30% × Uptime24h; `ReliabilityGradeOf` A ≥ 97 Swirl Legend · B ≥ 90 Dependable Dip · C ≥ 80 Coin Flip · D ≥ 70 Ask Before You Order · F Certified Broken; `LostSalesUsdOf` = DownHours7d × $42/h (≈12 treats × $3.49); `IsServingOf`; `CustomerHearsBrokenOf` = heat treat, mix low or Needs Service ("it's not broken, it's cleaning").
- Right to Repair: only TECH-001/008/011 are Taylor-certified (the rest withdrawn in `11_softserve.sql`), but every van carries the Taylor kit. `detour_stops.cypher` includes broken soft serve machines and takes `$rightToRepair`; the dashboard toggle does the same (7 → 17 fixable within 30 mi on 2026-11-01 evening).
- Pop-culture facts on the page were checked 2026-11-01: McDonald's tweet 11 Aug 2020 ("…our soft serve machine…"), McBroken (Rashiq Zahid, Oct 2020), ~4 h heat-treat cycle, Kytch lawsuits (2021), Copyright Office DMCA exemption 25 Oct 2024.

## Technician vans on the road
- Plan: `tools/valhalla.sh up` (Valhalla over the OpenStreetMap Arkansas extract from `~/arkansas-routing`, tiles copied into Docker volume `mcd-valhalla` because the bind mount is too slow), then `tools/plan_routes.py` → `sql/13_routes_data.sql` (generated, 2.8 MB, committed) and loads it; `tools/valhalla.sh down` after. Seeded per technician and day, so a re-run with the same stores and roads changes nothing.
- Shape: a 21-day rotation anchored on Monday 2026-11-02. Each workday a technician leaves their home store 07:15-08:00, does 3-5 service stops in their own patch (stores nearest their home store, within 70 mi; now and then one up to 45 mi away elsewhere in the territory), takes a 30-40 min lunch at the first job ending after 11:15, and is home 15:00-17:45. Valhalla orders the stops (`optimized_route`); each leg keeps its road shape (simplified to ~12 m) with seconds-after-departure from Valhalla's own maneuver times. Weekends: parked at home. 270 tech-days, 1,771 stops, 1,231 legs, ~108k road points. Longest leg ~3 h (north-central has 8 stores for 3 technicians).
- Positions are never stored. `fleet.truck_position_at(ts)` works them out from the plan in Arkansas local time (DST handled by Postgres): on site / lunch = the store, driving = interpolated along the road shape, otherwise parked at home. `api.v_truck_position_live` = now; `api.v_truck_track_recent` = every truck's last 7 days of road points and stops; `fleet.truck_track(tech, t0, t1)` any window. Each is ~1-6 ms.
- Atlas: `ServiceTruck` has `GpsLatitude`, `GpsLongitude`, `TruckStatus` (0 off duty, 10 driving, 20 on site, 30 lunch), `CurrentStoreId`, `NextStoreId`. The first four are served from the 7-day trail as time series (watermark on `Timestamp`), so UNWIND returns the route:
  `MATCH (k:ServiceTruck) WHERE k.TruckId = 'TRK-104' UNWIND k.GpsLatitude AS v WITH v WHERE v.Timestamp >= datetime('2026-11-04T12:00:00Z') RETURN v.Timestamp, v.Value`
  The type label in the MATCH is required — `MATCH (k)` silently returns only the current value.
- Dashboard: `/api/state` technicians carry the live fix (`lat/lon/status/at/next`, home store as `baseLat/baseLon`), so "who could fix it" distances are from where the van is now. `/api/truck/track?truck=TRK-101[&hours=12]` = the trail from Atlas (default since local midnight).

## Timebase version
Stack `timebase-2-0-beta` runs **2.0-gc6** (upgraded from gc4 on 2026-11-04). Its compose file is at
`~/timebase/timebase-2-0-beta/` (rebuilt from `docker inspect`), and gc4 volume backups are in
`~/timebase/backups/timebase-2-0-beta-gc4-2026-11-04/`. gc6 added validation rule O-B23, so every TVQ property
in `mcdonalds` now pins `Value` to `xsd:double` (range = TVQ ∩ Value:double). `atlas-common` `Tag.Data` got the
same pin on the Atlas `main` branch.

## Atlas dialect notes (this build)
Full repro for the Atlas team: `docs/atlas-cypher-silent-filter-bugs.md`. Gage gets these rules from the domain description and the `mcdonalds-ops-queries` skill (`atlas/skills/`, copied to `/atlas/config/skills/`, loaded at Atlas startup).
- Node variables carried through `WITH` are re-bound, not joined, by a later `MATCH`; carry scalars/lists (a later `MATCH … WHERE x.Id = t.Id` does join). Inline `{prop: value}` filters and end-node labels in a path are ignored — use `WHERE`.
- No trig functions and no `^`; `collect()` cannot be nested in another expression. A `MATCH` that finds nothing ends the pipeline — use `OPTIONAL MATCH` for things a technician might have none of.
- Timestamps come back as .NET ticks (`(ticks - 621355968000000000) / 1e7` = Unix seconds). Cypher REST: `POST /api/v1/branches/main/domains/mcdonalds-ops/queries {cypher, parameters}`.
- A `ReferenceStrategy` to a calculated property reads empty in Cypher (it still feeds a calculation on the same node); a cross-node `CalculatedStrategy` argument never fires.
- MCP library writes go to the admin identity's draft branch while it exists; publish with `git merge --ff-only` in `/atlas/config` only when the draft is strictly ahead of main. REST writes with the Claude token that fail validation open a `v2-draft/claude-*` session — publish with `POST /api/v1/branches/main/draft/publish`.

## Every table carries
`created_utc, modified_utc, is_deleted, deleted_utc, row_version` — `row_version` is the watermark (database-wide sequence, set by trigger). Never hard-delete.

## Expected compiled counts
1,221 instances (1 enterprise, 6 territories, 191 stores, 5×191 equipment, 18 technicians, 18 trucks, 5 certifications,
18 parts, 9 repair tasks); 19,657 edges (1,152 contains, 18,145 roadDistanceTo, 236 carriesPart, 42 holdsCertification,
18 each assignedTruck/basedAt/servesTerritory, 18 requiresPart, 10 requiresCertification).
