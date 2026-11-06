# Demo script (about 15 minutes)

Five short stories, each ending on one point about Timebase. The data is live, so store numbers and scores will
differ from the examples here. The people, certifications and vans in the stories never change.

**Before you start** (2 minutes): open http://127.0.0.1:8787 and check that the three tabs load with numbers, not
dashes. If anything is blank, see "Before a demo" in [SETUP.md](SETUP.md).

| Who | Role | Why they matter |
|---|---|---|
| **Darnell Brooks** (TECH-001, van TRK-101) | Senior, Little Rock | Fully certified; whatever he can't fix comes down to a part his van ran out of that day |
| **Priya Raman** (TECH-002, TRK-102) | Technician, Conway | Her Generac generator certificate lapsed 47 days ago, but she still carries generator parts |
| **Cody Whitfield** (TECH-003, TRK-103) | Apprentice, Little Rock | No EPA 608 or refrigeration certificates; not Taylor-certified for ice cream machines |
| **Curtis Webb** (TECH-013, TRK-113) | Senior, Southeast | His refrigeration certificate expires in 5 days |

---

## 1. Start with the ice cream machine (2 min)

**Tab: Soft Serve Finder.**

- The headline: how many of the 191 machines are broken right now.
- Type a ZIP (e.g. `72201`, Little Rock): nearest working machines, each with a reliability grade from A "Swirl
  Legend" to F "Certified Broken", and lost sales from downtime.
- Scroll to **Reliability matrix**: the two populations the data was built with, reliable and unreliable machines,
  are clearly visible.

**Point:** everyone has a broken ice cream machine story. Timebase took a raw on/off state signal from 191 machines
and turned it into uptime, mean time between failures, a grade and dollars lost. Nothing in the source data says
"F" or "$42 an hour".

## 2. Find the problems nobody has called in yet (3 min)

**Tab: Store Monitor.** Choose **All stores** (or a territory).

- Most units are green. Point at the amber and red ones that **are not in a fault state**: the store doesn't know
  yet.
- Open one red cooler. In **History**, its temperature has been creeping up for days, while the state tag still says
  "Holding". No alarm has fired.
- Explain the health index: last hour vs its own normal *and* vs the design normal (a cooler should hold 38 °F). A unit
  that has always run warm still gets caught.

**Point:** the controller says everything's fine. The pattern over time says otherwise. That's the gap between
alarms and a historian with a model on top.

## 3. Who can actually fix it? (4 min)

This is the core of the demo: a question that needs every data source at once.

**Scenario:** a technician is driving Little Rock (AR-20031) to West Memphis (AR-20039) on I-40, 167 road miles.
Which failing units are close enough to the route to be worth a stop, *and* can they fix them?

Ask Gage (in Atlas), or run it from a terminal:

```bash
tools/run_detour.py TECH-003 AR-20031 AR-20039      # Cody, the apprentice
tools/run_detour.py TECH-001 AR-20031 AR-20039      # Darnell, the senior
```

- **Cody** gets a few HVAC filter jobs as **STOP**, and a long list of **NEAR MISS**: freezers and coolers in danger,
  right on his route, that he can't fix. Each row says exactly why: `missing: level, EPA608, REFRIG, P-R404A…`
  (skill level, certifications, and parts not on his van).
- **Darnell**, on the same drive, can take almost all of them. His few near misses name a single part: whatever his
  van ran out of in that day's count (van stock is recounted every day, so the missing part changes).
- Each stop also shows the dollars at stake and the detour allowed: a freezer with $6,000 of product justifies a
  40-mile detour; a generator gets 5.

**Point:** this answer walks equipment health (Historian) → store → road distance → technician → certifications →
van → parts on board (Postgres), in **one Atlas query**. In most companies this is five systems and a phone call.

## 4. Watch the fleet (3 min)

**Tab: Fleet Tracker.**

- 18 vans moving on real Arkansas roads. Pins show who's driving and their status (driving, on site, lunch, off duty).
  Outside working hours they're parked at home; during the day, 3–5 stops each.
- Click a van: today's route, where it is now, the next stop and ETA, its certifications, and the road trail so far
  (the trail is history read back from Atlas).
- Click a red store: the nearest vans, and whether each is **certified** for that problem. The KPI at the top counts
  faults with a certified, on-duty van within 30 miles.
- Scroll to **Certifications**: every technician against every certificate. Point at Priya's expired GEN, Curtis's
  REFRIG expiring in 5 days, and the territories with no Taylor-certified technician at all.

**Point:** location, qualifications and live equipment condition on one screen. The nearest van isn't always the right
one.

## 5. Right to Repair (1 min)

Back on **Soft Serve Finder**, scroll to **Right to Repair** and flip the toggle.

- Only three technicians are Taylor-certified, but every van carries the Taylor repair kit. With the 2024 copyright
  exemption in force, any technician may repair the machine, and the number of broken machines that can be fixed
  within 30 miles jumps.
- From a terminal: `tools/run_detour.py TECH-003 AR-20031 AR-20039 --rtr` adds any broken ice cream machines near
  Cody's route (when none happen to be broken near I-40 at that moment, the list is unchanged; the dashboard toggle
  always has statewide numbers).

**Point:** a policy change is a one-line change to a rule in the model, and the answer to "what can we fix today"
updates everywhere.

---

## Closing (30 seconds)

Everything you saw stays current by itself: the equipment data streams continuously, the vans' positions come from
the clock, inventory is counted daily, and certification dates roll forward. Run the demo any day and it tells the
same stories with fresh numbers.

## Questions worth having ready

- **"Is this real McDonald's data?"** The 191 store locations are real public addresses. Everything else is simulated.
- **"Where does the health score come from?"** See "How it scores equipment health" in [OVERVIEW.md](OVERVIEW.md).
- **"Is the van tracking real GPS?"** No. It's a planned 21-day rotation driven on real road geometry
  (OpenStreetMap). Real GPS would come in through Connect in the same shape.
- **"What would it take with our data?"** Point Connect at the real HR/fleet/inventory databases and the Collector at
  the real controllers. The Atlas model stays the same.
