-- Read-only views for the service subject area. Clock-free except *_live. NULL never ''. Run as mcd_admin.

DROP VIEW IF EXISTS api.v_equipment_class;
CREATE VIEW api.v_equipment_class AS
SELECT equipment_class_code, name, tag_segment, health_signal,
       array_to_string(steady_state_codes, ',') AS steady_state_codes,
       normal_value::double precision AS normal_value, normal_tolerance::double precision AS normal_tolerance,
       unit_of_measure, product_at_risk_usd, max_detour_miles, consequence, modified_utc, row_version,
       downtime_revenue_per_hour_usd::double precision AS downtime_revenue_per_hour_usd
FROM ref.equipment_class WHERE NOT is_deleted;

CREATE OR REPLACE VIEW api.v_health_band AS
SELECT health_band_code, name, min_index::double precision AS min_index, is_detected, modified_utc, row_version
FROM ref.health_band WHERE NOT is_deleted;

CREATE OR REPLACE VIEW api.v_certification AS
SELECT certification_code, name, issuing_body, validity_years, modified_utc, row_version
FROM ref.certification WHERE NOT is_deleted;

CREATE OR REPLACE VIEW api.v_part AS
SELECT part_number, name, equipment_class_code, unit_cost_usd::double precision AS unit_cost_usd, modified_utc, row_version
FROM ref.part WHERE NOT is_deleted;

CREATE OR REPLACE VIEW api.v_repair_task AS
SELECT rt.repair_task_code, rt.name, rt.equipment_class_code, rt.health_band_code, rt.symptom,
       rt.min_cert_level_code, cl.level_rank AS min_level_rank, rt.est_minutes,
       (SELECT string_agg(c.certification_code, ',' ORDER BY c.certification_code)
          FROM ref.repair_task_certification c WHERE c.repair_task_code = rt.repair_task_code AND NOT c.is_deleted) AS required_certifications,
       (SELECT string_agg(p.part_number || ' x' || p.quantity, ',' ORDER BY p.part_number)
          FROM ref.repair_task_part p WHERE p.repair_task_code = rt.repair_task_code AND NOT p.is_deleted) AS required_parts,
       rt.modified_utc, rt.row_version,
       CASE rt.health_band_code WHEN 'WARNING' THEN 1 WHEN 'DANGER' THEN 2 WHEN 'FAULT' THEN 3 END AS condition_answered
FROM ref.repair_task rt
JOIN ref.cert_level cl ON cl.cert_level_code = rt.min_cert_level_code
WHERE NOT rt.is_deleted;

CREATE OR REPLACE VIEW api.v_repair_task_certification AS
SELECT repair_task_certification_id, repair_task_code, certification_code, modified_utc, row_version
FROM ref.repair_task_certification WHERE NOT is_deleted;

CREATE OR REPLACE VIEW api.v_repair_task_part AS
SELECT repair_task_part_id, repair_task_code, part_number, quantity, modified_utc, row_version
FROM ref.repair_task_part WHERE NOT is_deleted;

CREATE OR REPLACE VIEW api.v_technician AS
SELECT t.technician_id, t.first_name || ' ' || t.last_name AS full_name, t.first_name, t.last_name,
       t.cert_level_code, cl.name AS cert_level, cl.level_rank,
       t.home_territory_id, t.home_store_id, t.phone, t.hire_date,
       ta.truck_id AS current_truck_id, t.modified_utc, t.row_version
FROM hr.technician t
JOIN ref.cert_level cl ON cl.cert_level_code = t.cert_level_code
LEFT JOIN fleet.truck_assignment ta ON ta.technician_id = t.technician_id AND ta.end_date IS NULL AND NOT ta.is_deleted
WHERE NOT t.is_deleted;

-- Clock-relative: is_current compares expiry to today.
CREATE OR REPLACE VIEW api.v_technician_certification_live AS
SELECT tc.technician_certification_id, tc.technician_id, tc.certification_code, c.name AS certification,
       tc.certificate_number, tc.issued_date, tc.expires_date,
       (tc.expires_date IS NULL OR tc.expires_date >= current_date) AS is_current,
       tc.modified_utc, tc.row_version
FROM hr.technician_certification tc
JOIN ref.certification c ON c.certification_code = tc.certification_code
WHERE NOT tc.is_deleted;

CREATE OR REPLACE VIEW api.v_truck AS
SELECT f.truck_id, f.make, f.model, f.model_year, f.license_plate, f.home_territory_id,
       ta.technician_id AS current_technician_id, f.modified_utc, f.row_version
FROM fleet.truck f
LEFT JOIN fleet.truck_assignment ta ON ta.truck_id = f.truck_id AND ta.end_date IS NULL AND NOT ta.is_deleted
WHERE NOT f.is_deleted;

CREATE OR REPLACE VIEW api.v_truck_assignment AS
SELECT truck_assignment_id, truck_id, technician_id, start_date, end_date, (end_date IS NULL) AS is_current,
       modified_utc, row_version
FROM fleet.truck_assignment WHERE NOT is_deleted;

CREATE OR REPLACE VIEW api.v_truck_inventory_daily AS
SELECT truck_inventory_id, truck_id, inventory_date, part_number, quantity_on_hand, par_quantity,
       counted_by, is_restock_day, modified_utc, row_version
FROM fleet.truck_inventory_daily WHERE NOT is_deleted;

-- Latest count per truck (clock-free: "latest" is the newest inventory_date present, not today).
-- PK = TRUCK|PART so the topic keys stay stable from day to day.
CREATE OR REPLACE VIEW api.v_truck_inventory_current AS
SELECT i.truck_id || '|' || i.part_number AS truck_part_id, i.truck_id, i.part_number, i.inventory_date,
       i.quantity_on_hand, i.par_quantity, i.counted_by, i.modified_utc, i.row_version
FROM fleet.truck_inventory_daily i
WHERE NOT i.is_deleted
  AND i.inventory_date = (SELECT max(x.inventory_date) FROM fleet.truck_inventory_daily x
                          WHERE x.truck_id = i.truck_id AND NOT x.is_deleted);

CREATE OR REPLACE VIEW api.v_store_distance AS
SELECT store_distance_id, from_store_id, to_store_id, straight_miles::double precision AS straight_miles,
       road_miles::double precision AS road_miles, drive_minutes, modified_utc, row_version
FROM geo.store_distance WHERE NOT is_deleted;

GRANT USAGE ON SCHEMA api TO mcd_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA api TO mcd_reader;
