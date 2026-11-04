// Detour stops for a technician driving from one store to another.
// Parameters: $tech (e.g. 'TECH-001'), $origin (e.g. 'AR-20031'), $dest (e.g. 'AR-20039'),
//             $rightToRepair (true = the 2024 DMCA repair exemption applies: Taylor certification no longer required).
// A row = a drifting unit (ServiceCondition 1 Warning / 2 Danger, no fault showing) - or a soft serve machine that is
// down (condition 3, the ice cream machine is broken) - at an open store whose extra driving
// (origin->store->dest minus origin->dest) is within that unit's DetourAllowanceMiles, plus the repair task for it and
// whether this technician can do it now: level >= task minimum, every required certification held and current, every
// required part on today's truck count. verdict STOP = all three; NEAR MISS = lists what is missing.
// (held certifications / truck stock use OPTIONAL MATCH: a technician with no current certifications still gets rows.)
// Notes on the Atlas Cypher dialect: node variables are not joined across MATCH clauses, so each stage carries
// scalars/lists through WITH; inline {prop: value} filters are ignored (use WHERE); collect() cannot be nested.
MATCH (tech:Technician)-[:assignedTruck]->(k:ServiceTruck) WHERE tech.TechnicianId = $tech
WITH tech.Name AS techName, tech.LevelRank AS rank, k.TruckId AS truckId
OPTIONAL MATCH (t2:Technician)-[h:holdsCertification]->(c2:Certification) WHERE t2.TechnicianId = $tech AND h.IsCurrent = true
WITH techName, rank, truckId, collect(c2.CertificationCode) AS held
OPTIONAL MATCH (k2:ServiceTruck)-[cp:carriesPart]->(p2:Part) WHERE k2.TruckId = truckId AND cp.QuantityOnHand > 0
WITH techName, rank, truckId, held, collect(p2.PartNumber) AS stocked
MATCH (a:Store)-[d0:roadDistanceTo]-(b:Store) WHERE a.StoreId = $origin AND b.StoreId = $dest
WITH techName, rank, truckId, held, stocked, d0.RoadMiles AS direct
MATCH (o:Store)-[l1:roadDistanceTo]-(s:Store)-[l2:roadDistanceTo]-(x:Store), (s)-[:contains]->(e)
WHERE o.StoreId = $origin AND x.StoreId = $dest AND s.IsOpen = true
  AND (e.ServiceCondition.Value IN [1, 2] OR (e.EquipmentClassCode = 'SOFTSERVE' AND e.ServiceCondition.Value = 3))
  AND l1.RoadMiles + l2.RoadMiles - direct <= e.DetourAllowanceMiles.Value
WITH techName, rank, truckId, held, stocked, s.StoreId AS store, s.City AS city, e.EquipmentClassCode AS cls,
     e.ServiceCondition.Value AS cond, e.HealthIndex.Value AS hi, e.ExposureUsd.Value AS usd,
     round(l1.RoadMiles + l2.RoadMiles - direct, 1) AS detour, e.DetourAllowanceMiles.Value AS allowance
MATCH (t:RepairTask) WHERE t.EquipmentClassCode = cls AND t.ConditionAnswered = cond
OPTIONAL MATCH (t)-[:requiresCertification]->(rc:Certification)
WITH techName, rank, truckId, held, stocked, store, city, cls, cond, hi, usd, detour, allowance, t,
     collect(DISTINCT rc.CertificationCode) AS reqCerts
OPTIONAL MATCH (t)-[:requiresPart]->(rp:Part)
WITH techName, rank, truckId, held, stocked, store, city, cls, cond, hi, usd, detour, allowance, t, reqCerts,
     collect(DISTINCT rp.PartNumber) AS reqParts
WITH techName, truckId, store, city, cls, cond, hi, usd, detour, allowance, t.RepairTaskCode AS task, t.EstMinutes AS minutes,
     rank >= t.MinLevelRank AS levelOk,
     [c IN reqCerts WHERE c IS NOT NULL AND NOT c IN held AND NOT (c = 'TAYLOR' AND $rightToRepair)] AS missingCerts,
     [p IN reqParts WHERE p IS NOT NULL AND NOT p IN stocked] AS missingParts
RETURN techName, truckId, store, city, cls, cond, hi, detour, allowance, usd, task, minutes, levelOk, missingCerts, missingParts,
       CASE WHEN levelOk AND size(missingCerts) = 0 AND size(missingParts) = 0 THEN 'STOP' ELSE 'NEAR MISS' END AS verdict
ORDER BY verdict DESC, usd DESC
