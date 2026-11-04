-- Views for the soft-serve finder. Run as mcd_admin. Clock-free.
CREATE OR REPLACE VIEW api.v_zip_code AS
SELECT zip, latitude::double precision AS latitude, longitude::double precision AS longitude, modified_utc, row_version
FROM geo.zip_code WHERE NOT is_deleted;

GRANT SELECT ON ALL TABLES IN SCHEMA api TO mcd_reader;
