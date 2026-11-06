-- Hard-coded expected state after 05-09, asserted against the demo anchor 2026-11-01 (never current_date).
-- Inventory checks cover only the seeded window 2026-10-03..2026-11-01; days added later by the daily job are ignored.
WITH c(check_name, actual, expected) AS (VALUES
 ('equipment classes with a health signal', (SELECT count(*) FROM ref.equipment_class WHERE health_signal IS NOT NULL)::text, '4'),
 ('max detour miles by class', (SELECT string_agg(equipment_class_code||'='||max_detour_miles, ',' ORDER BY equipment_class_code) FROM ref.equipment_class),
   'COOLER=30,FREEZER=40,GENERATOR=5,HVAC=15,SOFTSERVE=10'),
 ('health bands',          (SELECT count(*) FROM ref.health_band)::text, '4'),
 ('cert levels',           (SELECT count(*) FROM ref.cert_level)::text, '3'),
 ('certifications',        (SELECT count(*) FROM ref.certification)::text, '5'),
 ('parts',                 (SELECT count(*) FROM ref.part)::text, '18'),
 ('repair tasks',          (SELECT count(*) FROM ref.repair_task)::text, '9'),
 ('repair task certs',     (SELECT count(*) FROM ref.repair_task_certification)::text, '10'),
 ('repair task parts',     (SELECT count(*) FROM ref.repair_task_part)::text, '18'),
 ('technicians',           (SELECT count(*) FROM hr.technician)::text, '18'),
 ('technicians per level', (SELECT string_agg(cert_level_code||'='||n, ',' ORDER BY cert_level_code) FROM (SELECT cert_level_code, count(*) n FROM hr.technician GROUP BY 1) x),
   'APPRENTICE=6,SENIOR=6,TECHNICIAN=6'),
 ('technician certs',      (SELECT count(*) FROM hr.technician_certification)::text, '53'),
 ('certs lapsed at anchor',(SELECT string_agg(technician_certification_id, ',') FROM hr.technician_certification WHERE expires_date < '2026-11-01'), 'TECH-002|GEN'),
 ('home store in own territory', (SELECT count(*) FROM hr.technician t JOIN org.store s ON s.store_id = t.home_store_id WHERE s.territory_id <> t.home_territory_id)::text, '0'),
 ('trucks',                (SELECT count(*) FROM fleet.truck)::text, '18'),
 ('assignments',           (SELECT count(*) FROM fleet.truck_assignment)::text, '19'),
 ('current assignments',   (SELECT count(*) FROM fleet.truck_assignment WHERE end_date IS NULL)::text, '18'),
 ('technicians without a truck', (SELECT count(*) FROM api.v_technician WHERE current_truck_id IS NULL)::text, '0'),
 ('par levels',            (SELECT count(*) FROM fleet.truck_par_level)::text, '236'),
 ('deliberate zero par',   (SELECT string_agg(truck_par_level_id, ',') FROM fleet.truck_par_level WHERE par_quantity = 0), 'TRK-103|P-GSK-CLR'),
 ('inventory rows (seed window)', (SELECT count(*) FROM fleet.truck_inventory_daily WHERE inventory_date BETWEEN '2026-10-03' AND '2026-11-01')::text, '7080'),
 ('inventory days (seed window)', (SELECT count(DISTINCT inventory_date) FROM fleet.truck_inventory_daily WHERE inventory_date BETWEEN '2026-10-03' AND '2026-11-01')::text, '30'),
 ('stockouts at anchor',   (SELECT count(*) FROM fleet.truck_inventory_daily WHERE inventory_date = '2026-11-01' AND quantity_on_hand = 0 AND par_quantity > 0)::text, '40'),
 ('TRK-101 stockouts at anchor', (SELECT string_agg(part_number, ',' ORDER BY part_number) FROM fleet.truck_inventory_daily WHERE truck_id = 'TRK-101' AND inventory_date = '2026-11-01' AND quantity_on_hand = 0), 'P-R410A'),
 ('over par',              (SELECT count(*) FROM fleet.truck_inventory_daily WHERE quantity_on_hand > par_quantity)::text, '0'),
 ('every task part stocked somewhere', (SELECT count(*) FROM ref.repair_task_part rp WHERE NOT EXISTS (SELECT 1 FROM fleet.truck_par_level pl WHERE pl.part_number = rp.part_number AND pl.par_quantity > 0))::text, '0'),
 ('store distances',       (SELECT count(*) FROM geo.store_distance)::text, '18145'),
 ('AR-20031 to AR-20039 road miles', (SELECT road_miles::text FROM geo.store_distance WHERE store_distance_id = 'AR-20031|AR-20039'), '167.3'),
 ('active technician certs', (SELECT count(*) FROM hr.technician_certification WHERE NOT is_deleted)::text, '42'),
 ('Taylor-certified technicians', (SELECT string_agg(technician_id, ',' ORDER BY technician_id) FROM api.v_technician_certification_live WHERE certification_code = 'TAYLOR'), 'TECH-001,TECH-008,TECH-011'),
 ('Cody has no Taylor cert', (SELECT count(*) FROM api.v_technician_certification_live WHERE technician_id = 'TECH-003' AND certification_code = 'TAYLOR')::text, '0'),
 ('every truck carries Taylor parts', (SELECT count(DISTINCT truck_id) FROM fleet.truck_par_level WHERE part_number IN ('P-TAY-KIT','P-TAY-BLADE') AND par_quantity > 0)::text, '18'),
 ('soft serve downtime $/hour', (SELECT downtime_revenue_per_hour_usd::text FROM ref.equipment_class WHERE equipment_class_code = 'SOFTSERVE'), '42.00'),
 ('Arkansas ZIP centroids', (SELECT count(*) FROM geo.zip_code)::text, '615'),
 ('store ZIPs without a centroid', (SELECT count(*) FROM org.store s WHERE NOT EXISTS (SELECT 1 FROM geo.zip_code z WHERE z.zip = s.zip))::text, '0'),
 ('route plan: tech-days', (SELECT count(DISTINCT (technician_id, rotation_day)) FROM fleet.route_stop WHERE NOT is_deleted)::text, '270'),
 ('route plan: stops / legs', (SELECT count(*) FROM fleet.route_stop WHERE NOT is_deleted)::text || ' / ' || (SELECT count(*) FROM fleet.route_leg WHERE NOT is_deleted)::text, '1771 / 1231'),
 ('route plan: no weekend driving', (SELECT count(*) FROM fleet.route_stop WHERE NOT is_deleted AND rotation_day % 7 >= 5)::text, '0'),
 ('route plan: days end 15:00-17:45', (SELECT count(*) FROM fleet.route_stop WHERE NOT is_deleted AND stop_kind = 'END' AND arrive_sec NOT BETWEEN 15*3600 - 60 AND 17*3600 + 45*60)::text, '0'),
 ('route plan: every leg starts and ends at its stores', (SELECT count(*) FROM fleet.route_leg l JOIN org.store a ON a.store_id = l.from_store_id JOIN org.store b ON b.store_id = l.to_store_id
      WHERE NOT l.is_deleted AND (abs(l.lat[1] - a.latitude::float8) > 0.01 OR abs(l.lat[cardinality(l.lat)] - b.latitude::float8) > 0.01))::text, '0'),
 ('TECH-001 Thursday 10:40 (rotation day 3)', (SELECT status || ' ' || coalesce(store_id, '') FROM fleet.truck_position_at('2026-11-05 10:40 America/Chicago') WHERE technician_id = 'TECH-001'), 'On site AR-20191'),
 ('Saturday: all 18 vans off duty', (SELECT count(*) FROM fleet.truck_position_at('2026-11-07 10:40 America/Chicago') WHERE status = 'Off duty')::text, '18'),
 ('live view has 18 vans', (SELECT count(*) FROM api.v_truck_position_live)::text, '18'),
 ('cert dates roll with the calendar: Curtis REFRIG days left', (SELECT days_to_expiry::text FROM api.v_technician_certification_live WHERE technician_certification_id = 'TECH-013|REFRIG'), '5'),
 ('cert dates roll with the calendar: expiry = today + days left', (SELECT count(*) FROM api.v_technician_certification_live WHERE expires_date IS DISTINCT FROM current_date + days_to_expiry)::text, '0'),
 ('certs lapsed (live)', (SELECT string_agg(technician_certification_id, ',') FROM api.v_technician_certification_live WHERE NOT is_current), 'TECH-002|GEN'),
 ('zero row_version', (SELECT count(*) FROM (
      SELECT row_version FROM hr.technician UNION ALL SELECT row_version FROM hr.technician_certification
      UNION ALL SELECT row_version FROM fleet.truck UNION ALL SELECT row_version FROM fleet.truck_assignment
      UNION ALL SELECT row_version FROM fleet.truck_par_level UNION ALL SELECT row_version FROM fleet.truck_inventory_daily
      UNION ALL SELECT row_version FROM geo.store_distance UNION ALL SELECT row_version FROM ref.repair_task
      UNION ALL SELECT row_version FROM ref.part UNION ALL SELECT row_version FROM fleet.route_stop
      UNION ALL SELECT row_version FROM fleet.route_leg) x WHERE row_version = 0)::text, '0')
)
SELECT CASE WHEN actual = expected THEN 'PASS' ELSE 'FAIL' END AS result, check_name, actual, expected FROM c;
