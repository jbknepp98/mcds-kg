// Health matrix: every store x {cooler, freezer, HVAC, generator}. Each cell = HealthIndex/ServiceCondition
// (index 0-100; condition 0 healthy, 1 warning undetected, 2 danger undetected, 3 fault detected). Worst first.
MATCH (t:Territory)-[:contains]->(s:Store)-[:contains]->(e)
WHERE e.EquipmentClassCode IN ['COOLER','FREEZER','HVAC','GENERATOR']
WITH t.Name AS territory, s.StoreId AS store, s.City AS city,
     collect(e.EquipmentClassCode + '=' + toString(e.HealthIndex.Value) + '/' + toString(e.ServiceCondition.Value)) AS cells,
     min(e.HealthIndex.Value) AS worst
RETURN territory, store, city, worst, cells ORDER BY worst
