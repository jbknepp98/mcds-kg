-- Hard-coded expected state after 00-04. Every row must say PASS.
WITH c(check_name, actual, expected) AS (VALUES
 ('territories',            (SELECT count(*) FROM org.territory)::text, '6'),
 ('stores',                 (SELECT count(*) FROM org.store)::text, '191'),
 ('store id range',         (SELECT min(store_id)||'..'||max(store_id) FROM org.store), 'AR-20010..AR-20200'),
 ('counties',               (SELECT count(*) FROM ref.county)::text, '62'),
 ('cities',                 (SELECT count(DISTINCT city) FROM org.store)::text, '98'),
 ('status ACTIVE',          (SELECT count(*) FROM org.store WHERE operating_status_code='ACTIVE')::text, '170'),
 ('status TEMP_CLOSED',     (SELECT count(*) FROM org.store WHERE operating_status_code='TEMP_CLOSED')::text, '16'),
 ('status CLOSED',          (SELECT count(*) FROM org.store WHERE operating_status_code='CLOSED')::text, '5'),
 ('type FREESTANDING',      (SELECT count(*) FROM org.store WHERE location_type_code='FREESTANDING')::text, '147'),
 ('type GAS_STATION',       (SELECT count(*) FROM org.store WHERE location_type_code='GAS_STATION')::text, '26'),
 ('type WALMART',           (SELECT count(*) FROM org.store WHERE location_type_code='WALMART')::text, '18'),
 ('per territory',          (SELECT string_agg(territory_id||'='||n, ',' ORDER BY territory_id) FROM (SELECT territory_id, count(*) n FROM org.store GROUP BY 1) x),
   'territory-central-arkansas=43,territory-north-central-arkansas=8,territory-northeast-arkansas=27,territory-northwest-arkansas=50,territory-southeast-arkansas=29,territory-southwest-arkansas=34'),
 ('null drive_thru_hours',  (SELECT count(*) FROM org.store WHERE drive_thru_hours IS NULL)::text, '23'),
 ('empty strings',          (SELECT count(*) FROM org.store WHERE '' IN (display_name,address,city,zip,phone,restaurant_hours,drive_thru_hours))::text, '0'),
 ('brand McDonald''s only', (SELECT count(*) FROM org.store WHERE restaurant_name <> 'McDonald''s' OR display_name LIKE '%McDowell%')::text, '0'),
 ('AR-20031 exact coords',  (SELECT latitude||','||longitude FROM org.store WHERE store_id='AR-20031'), '34.773436,-92.360990'),
 ('equipment classes',      (SELECT count(*) FROM ref.equipment_class)::text, '5'),
 ('zero row_version',       (SELECT count(*) FROM (SELECT row_version FROM org.store UNION ALL SELECT row_version FROM org.territory) x WHERE row_version = 0)::text, '0'),
 ('api.v_store rows',       (SELECT count(*) FROM api.v_store)::text, '191'),
 ('api.v_territory sum',    (SELECT sum(store_count) FROM api.v_territory)::text, '191')
)
SELECT CASE WHEN actual = expected THEN 'PASS' ELSE 'FAIL' END AS result, check_name, actual, expected FROM c;
