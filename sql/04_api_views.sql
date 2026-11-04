-- Read-only views Connect polls. Clock-free; NULL never ''. Run as mcd_admin.
CREATE OR REPLACE VIEW api.v_territory AS
SELECT t.territory_id, t.name,
       (SELECT count(*) FROM org.store s WHERE s.territory_id = t.territory_id AND NOT s.is_deleted) AS store_count,
       t.modified_utc, t.row_version
FROM org.territory t
WHERE NOT t.is_deleted;

CREATE OR REPLACE VIEW api.v_store AS
SELECT s.store_id, s.store_number, s.display_name, s.territory_id, t.name AS territory_name,
       s.restaurant_name, s.address, s.city, s.state_code, s.zip, s.county_code, c.name AS county_name,
       s.latitude::double precision AS latitude, s.longitude::double precision AS longitude, s.phone,
       s.operating_status_code, os.name AS operating_status, os.is_open,
       s.location_type_code, lt.name AS location_type,
       s.restaurant_hours, s.drive_thru_hours, s.is_24_hour, s.has_drive_thru, s.has_mobile_ordering,
       s.has_delivery, s.has_kiosk, s.has_play_place,
       s.modified_utc, s.row_version
FROM org.store s
JOIN org.territory t        ON t.territory_id = s.territory_id
JOIN ref.county c           ON c.county_code = s.county_code
JOIN ref.operating_status os ON os.operating_status_code = s.operating_status_code
JOIN ref.location_type lt   ON lt.location_type_code = s.location_type_code
WHERE NOT s.is_deleted;

-- api.v_equipment_class lives in 09_api_views_service.sql (it carries the health/consequence columns).

GRANT USAGE ON SCHEMA api TO mcd_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA api TO mcd_reader;
