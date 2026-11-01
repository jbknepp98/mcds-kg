-- Reference vocabularies. Run as mcd_admin. Re-runnable (upserts).
CREATE TABLE IF NOT EXISTS ref.location_type (
  location_type_code text PRIMARY KEY,
  name               text NOT NULL UNIQUE
);
CALL util.add_audit('ref.location_type');
INSERT INTO ref.location_type VALUES
  ('FREESTANDING','Freestanding'), ('GAS_STATION','Gas Station'), ('WALMART','Wal*Mart')
ON CONFLICT (location_type_code) DO UPDATE SET name = EXCLUDED.name
  WHERE ref.location_type.name IS DISTINCT FROM EXCLUDED.name;

CREATE TABLE IF NOT EXISTS ref.operating_status (
  operating_status_code text PRIMARY KEY,
  name                  text NOT NULL UNIQUE,
  is_open               boolean NOT NULL
);
CALL util.add_audit('ref.operating_status');
INSERT INTO ref.operating_status VALUES
  ('ACTIVE','Active',true), ('TEMP_CLOSED','Temporarily Closed',false), ('CLOSED','Closed',false)
ON CONFLICT (operating_status_code) DO UPDATE SET name = EXCLUDED.name, is_open = EXCLUDED.is_open
  WHERE (ref.operating_status.name, ref.operating_status.is_open) IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.is_open);

-- Counties are loaded by 03_org.sql from the store seed (only counties that have stores).
CREATE TABLE IF NOT EXISTS ref.county (
  county_code text PRIMARY KEY,          -- slug of the name, e.g. 'pulaski'
  name        text NOT NULL UNIQUE,      -- 'Pulaski County'
  state_code  char(2) NOT NULL DEFAULT 'AR'
);
CALL util.add_audit('ref.county');

-- Store equipment classes; tag_segment is the simulator tag segment: AR-20031.<tag_segment>.<signal>
CREATE TABLE IF NOT EXISTS ref.equipment_class (
  equipment_class_code text PRIMARY KEY,
  name                 text NOT NULL UNIQUE,
  tag_segment          text NOT NULL UNIQUE
);
CALL util.add_audit('ref.equipment_class');
INSERT INTO ref.equipment_class VALUES
  ('COOLER','Walk-in Cooler','Cooler'), ('FREEZER','Walk-in Freezer','Freezer'),
  ('HVAC','Rooftop HVAC Unit','HVAC'), ('GENERATOR','Backup Generator','Generator'),
  ('SOFTSERVE','Soft Serve Machine','SoftServe')
ON CONFLICT (equipment_class_code) DO UPDATE SET name = EXCLUDED.name, tag_segment = EXCLUDED.tag_segment
  WHERE (ref.equipment_class.name, ref.equipment_class.tag_segment) IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.tag_segment);
