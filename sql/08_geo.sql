-- Store-to-store distances for detour maths (Atlas Cypher has no trig, so distances are precomputed).
-- road_miles = great-circle miles x 1.3 circuity; drive_minutes at a 50 mph average.
-- One row per unordered pair, from_store_id < to_store_id. PK = FROM|TO. Run as mcd_admin. Re-runnable.
CREATE SCHEMA IF NOT EXISTS geo;

CREATE TABLE IF NOT EXISTS geo.store_distance (
  store_distance_id text PRIMARY KEY,
  from_store_id     text NOT NULL REFERENCES org.store,
  to_store_id       text NOT NULL REFERENCES org.store,
  straight_miles    numeric(6,1) NOT NULL,
  road_miles        numeric(6,1) GENERATED ALWAYS AS (round(straight_miles * 1.3, 1)) STORED,
  drive_minutes     integer      GENERATED ALWAYS AS (round(straight_miles * 1.3 / 50 * 60)::integer) STORED,
  CHECK (from_store_id < to_store_id),
  CHECK (store_distance_id = from_store_id || '|' || to_store_id)
);
CALL util.add_audit('geo.store_distance');

INSERT INTO geo.store_distance (store_distance_id, from_store_id, to_store_id, straight_miles)
SELECT a.store_id || '|' || b.store_id, a.store_id, b.store_id,
       round((3958.8 * 2 * asin(sqrt(
          power(sin(radians((b.latitude - a.latitude)::float8) / 2), 2)
        + cos(radians(a.latitude::float8)) * cos(radians(b.latitude::float8))
        * power(sin(radians((b.longitude - a.longitude)::float8) / 2), 2))))::numeric, 1)
FROM org.store a JOIN org.store b ON a.store_id < b.store_id
WHERE NOT a.is_deleted AND NOT b.is_deleted
ON CONFLICT (store_distance_id) DO UPDATE SET straight_miles = EXCLUDED.straight_miles
  WHERE geo.store_distance.straight_miles IS DISTINCT FROM EXCLUDED.straight_miles;
