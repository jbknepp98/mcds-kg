-- Territories (regions) and stores. Run as mcd_admin. Data comes from 03_org_data.sql.
CREATE TABLE IF NOT EXISTS org.territory (
  territory_id text PRIMARY KEY,                 -- 'territory-central-arkansas' (same ID as grit)
  name         text NOT NULL UNIQUE              -- 'Central Arkansas'
);
CALL util.add_audit('org.territory');

CREATE TABLE IF NOT EXISTS org.store (
  store_id              text PRIMARY KEY CHECK (store_id ~ '^AR-[0-9]{5}$'),   -- 'AR-20031'
  store_number          integer GENERATED ALWAYS AS (substr(store_id,4)::integer) STORED UNIQUE,
  display_name          text NOT NULL,           -- "Little Rock McDonald's (AR-20031)"
  territory_id          text NOT NULL REFERENCES org.territory,
  restaurant_name       text NOT NULL,
  address               text NOT NULL,
  city                  text NOT NULL,
  state_code            char(2) NOT NULL,
  zip                   text NOT NULL CHECK (zip ~ '^[0-9]{5}$'),
  county_code           text NOT NULL REFERENCES ref.county,
  latitude              numeric(9,6) NOT NULL CHECK (latitude BETWEEN 33 AND 36.6),
  longitude             numeric(9,6) NOT NULL CHECK (longitude BETWEEN -94.7 AND -89.6),
  phone                 text,
  operating_status_code text NOT NULL REFERENCES ref.operating_status,
  location_type_code    text NOT NULL REFERENCES ref.location_type,
  restaurant_hours      text,
  drive_thru_hours      text,                    -- NULL where source had none
  is_24_hour            boolean NOT NULL,
  has_drive_thru        boolean NOT NULL,
  has_mobile_ordering   boolean NOT NULL,
  has_delivery          boolean NOT NULL,
  has_kiosk             boolean NOT NULL,
  has_play_place        boolean NOT NULL
);
CALL util.add_audit('org.store');
CREATE INDEX IF NOT EXISTS ix_store_territory ON org.store (territory_id);
