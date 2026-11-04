---
description: "Write correct Cypher for the mcdonalds-ops domain (McDonald's Arkansas stores, territories, equipment health, ice cream machines, technicians, trucks, parts, certifications, distances). Load before ANY query against mcdonalds-ops - this Atlas build has Cypher traps that silently return wrong rows."
user-invocable: true
disable-model-invocation: false
---
# Querying mcdonalds-ops correctly

This Atlas build's Cypher engine has traps that return plausible but WRONG rows without any error. Follow these
rules for every query against the `mcdonalds-ops` domain.

## Rules (never break these)

1. **Never use inline property maps.** `MATCH (s:Store {StoreId: 'AR-20086'})` or `{StoreId: t.HomeStoreId}` is
   silently IGNORED and matches every store. Always filter in `WHERE`: `MATCH (s:Store) WHERE s.StoreId = 'AR-20086'`.
2. **Never re-use a node variable in a later MATCH.** `MATCH (s:Store) WHERE ... WITH s MATCH (t)-[:basedAt]->(s)`
   does NOT join on `s` - it re-binds `s` to anything. Put the whole path and its filters in ONE `MATCH ... WHERE`.
   Only scalars and lists (e.g. `WITH s.StoreId AS sid` then `WHERE x.StoreId = sid`) carry safely between stages.
3. **Join through relationships, not matching property values.** A technician's home store is
   `(t:Technician)-[:basedAt]->(h:Store)`, never `MATCH (h:Store {StoreId: t.HomeStoreId})` (inline map: ignored,
   pairs every technician with all 191 stores). A second `MATCH (h:Store) WHERE h.StoreId = t.HomeStoreId` does
   join correctly, but the relationship is simpler and is the pattern to use.
4. **No trig, no `^`, no `point.distance`.** Distances between stores are precomputed as `roadDistanceTo` edges
   (one edge per pair, match it UNDIRECTED: `-[d:roadDistanceTo]-`) with `d.RoadMiles` and `d.DriveMinutes`.
   A store has no distance edge to itself.
5. **Labels on a pattern's end node may be ignored** - when you need one equipment class, also filter
   `WHERE e.EquipmentClassCode = 'SOFTSERVE'` (COOLER, FREEZER, HVAC, GENERATOR, SOFTSERVE).
6. **A MATCH that finds nothing ends the query.** Use `OPTIONAL MATCH` for things that may be absent
   (a technician with no current certifications, a truck with no stock of a part). After an empty OPTIONAL MATCH,
   `collect(...)` returns `[null]` - filter with `[x IN list WHERE x IS NOT NULL]`.
7. **Live values are TVQ compounds**: read `.Value` (e.g. `e.HealthIndex.Value`). `.Timestamp` comes back as
   .NET ticks.
8. **Sanity-check before answering.** If a column that should vary (home store, city, distance) has the SAME value
   on every row, the query is wrong - re-check rules 1-3 and re-run. Never report "all 18 technicians are based at X"
   without checking each row's own `basedAt` store.

## Model in one paragraph

Enterprise `McDonalds-AR` -contains-> 6 `Territory` -contains-> 191 `Store` (StoreId `AR-20010`..`AR-20200`, Address,
City, Zip, Latitude, Longitude, IsOpen, OperatingStatus). Each store -contains-> Cooler, Freezer, HVACUnit,
Generator, SoftServeMachine (instance ids `<StoreId>-Cooler` etc.; `StoreId` and `EquipmentClassCode` on each).
Monitored units carry `HealthIndex` (0-100), `ServiceCondition` (0 healthy, 1 warning undetected, 2 danger
undetected, 3 fault detected), `DetourAllowanceMiles`, `ExposureUsd`. Soft serve machines carry `SoftServeState`
(0 serving, 10 heat treat, 20 mix low, 40 needs service), `IsServing`, `CustomerHearsBroken`, `Uptime24h`, `Uptime7d`,
`Serving7d`, `Failures7d`, `MtbfHours`, `MttrHours`, `DownMinutes`, `ReliabilityScore`, `ReliabilityGrade`
(4 A .. 0 F), `LostSalesUsd7d`. 18 `Technician` (TechnicianId, Name, CertLevel, LevelRank 1-3, HomeStoreId)
-basedAt-> Store, -servesTerritory-> Territory, -assignedTruck-> `ServiceTruck` -carriesPart {QuantityOnHand,
ParQuantity, InventoryDate}-> `Part`; -holdsCertification {IsCurrent, ExpiresDate}-> `Certification`.
`RepairTask` (EquipmentClassCode, ConditionAnswered, MinLevelRank) -requiresCertification-> Certification,
-requiresPart {Quantity}-> Part.

## Patterns that work

Technicians within N road miles of a store (plus anyone based AT that store):
```cypher
MATCH (t:Technician)-[:basedAt]->(h:Store)-[d:roadDistanceTo]-(s:Store)
WHERE s.StoreId = $store AND d.RoadMiles <= $miles
RETURN t.Name, t.CertLevel, h.StoreId AS home, h.City AS homeCity, d.RoadMiles AS roadMiles ORDER BY roadMiles
```
```cypher
MATCH (t:Technician)-[:basedAt]->(h:Store) WHERE h.StoreId = $store RETURN t.Name, t.CertLevel
```

Every technician's home store:
```cypher
MATCH (t:Technician)-[:basedAt]->(h:Store) RETURN t.TechnicianId, t.Name, h.StoreId, h.Address, h.City ORDER BY t.TechnicianId
```

Find a store by street/city first, then use its StoreId as a literal or parameter in the next query:
```cypher
MATCH (s:Store) WHERE toLower(s.City) = 'bentonville' AND toLower(s.Address) CONTAINS 'walton' RETURN s.StoreId, s.Address
```

Closest working ice cream machines to a store:
```cypher
MATCH (s:Store)-[d:roadDistanceTo]-(o:Store)-[:contains]->(m)
WHERE s.StoreId = $store AND m.EquipmentClassCode = 'SOFTSERVE' AND o.IsOpen = true AND m.SoftServeState.Value = 0
RETURN o.StoreId, o.City, o.Address, d.RoadMiles, m.ReliabilityGrade.Value ORDER BY d.RoadMiles LIMIT 5
```

Health matrix for one store:
```cypher
MATCH (s:Store)-[:contains]->(e) WHERE s.StoreId = $store
RETURN e.EquipmentClassCode, e.HealthIndex.Value, e.ServiceCondition.Value, e.SoftServeState.Value
```

What a technician can fix (level, current certifications, today's truck stock): carry lists through WITH, e.g.
```cypher
MATCH (t:Technician)-[:assignedTruck]->(k:ServiceTruck) WHERE t.TechnicianId = $tech
WITH t.LevelRank AS rank, k.TruckId AS truckId
OPTIONAL MATCH (t2:Technician)-[h:holdsCertification]->(c:Certification) WHERE t2.TechnicianId = $tech AND h.IsCurrent = true
WITH rank, truckId, collect(c.CertificationCode) AS held
OPTIONAL MATCH (k2:ServiceTruck)-[cp:carriesPart]->(p:Part) WHERE k2.TruckId = truckId AND cp.QuantityOnHand > 0
RETURN rank, held, collect(p.PartNumber) AS stocked
```
Route detours (stores worth stopping at between two stores, checked against skills and parts): the full query
is maintained in the repo as `atlas/queries/detour_stops.cypher` (parameters `$tech`, `$origin`, `$dest`,
`$rightToRepair`).
