-- Service reference data: equipment health/consequence settings, health bands, technician levels,
-- certifications, parts, repair tasks. Run as mcd_admin. Re-runnable (upserts).

-- Equipment class: what "normal" looks like for the health index, and what a miss costs.
--   health_signal      simulator measure the health index is computed from (NULL = state only)
--   steady_state_codes states that count as normal running for the baseline + 1h average
--   normal_value/_tolerance  design normal for the steady-state 1h average (one-sided: only high is bad)
--   product_at_risk_usd / max_detour_miles  consequence of a miss; drives DetourAllowanceMiles in Atlas
ALTER TABLE ref.equipment_class
  ADD COLUMN IF NOT EXISTS health_signal       text,
  ADD COLUMN IF NOT EXISTS steady_state_codes  integer[],
  ADD COLUMN IF NOT EXISTS normal_value        numeric(6,1),
  ADD COLUMN IF NOT EXISTS normal_tolerance    numeric(5,1),
  ADD COLUMN IF NOT EXISTS unit_of_measure     text,
  ADD COLUMN IF NOT EXISTS product_at_risk_usd integer,
  ADD COLUMN IF NOT EXISTS max_detour_miles    integer,
  ADD COLUMN IF NOT EXISTS consequence         text;

UPDATE ref.equipment_class e SET
  health_signal = v.sig, steady_state_codes = v.ss, normal_value = v.nv, normal_tolerance = v.nt,
  unit_of_measure = v.uom, product_at_risk_usd = v.usd, max_detour_miles = v.mi, consequence = v.why
FROM (VALUES
  ('COOLER',    'Temperature',          ARRAY[20],    38.0, 1.0, '°F', 3500, 30, 'Dairy, produce and sauces spoil above 41 °F'),
  ('FREEZER',   'Temperature',          ARRAY[20],    -4.0, 2.0, '°F', 6000, 40, 'Frozen beef patties, fries and nuggets are lost if the box thaws'),
  ('HVAC',      'SupplyAirTemperature', ARRAY[20],    58.0, 3.0, '°F',  800, 15, 'Crew comfort and kitchen heat; dining-room complaints'),
  ('GENERATOR', 'LoadPercent',          ARRAY[10,30], 70.0, 6.0, '%',   300,  5, 'Storm backup only; no impact unless the grid fails'),
  ('SOFTSERVE', NULL,                   NULL,         NULL, NULL, NULL, 400, 10, 'McFlurry and cone sales lost (just for fun)')
) v(code, sig, ss, nv, nt, uom, usd, mi, why)
WHERE e.equipment_class_code = v.code
  AND (e.health_signal, e.steady_state_codes, e.normal_value, e.normal_tolerance, e.unit_of_measure,
       e.product_at_risk_usd, e.max_detour_miles, e.consequence)
      IS DISTINCT FROM (v.sig, v.ss, v.nv, v.nt, v.uom, v.usd, v.mi, v.why);

-- Health bands. Index bands match the Atlas HealthIndex function; FAULT = state code 40+ (already detected).
CREATE TABLE IF NOT EXISTS ref.health_band (
  health_band_code text PRIMARY KEY,
  name             text NOT NULL UNIQUE,
  min_index        numeric(5,1),            -- inclusive lower bound of the 0-100 index (NULL for FAULT)
  is_detected      boolean NOT NULL         -- true = the store already knows (a fault state is showing)
);
CALL util.add_audit('ref.health_band');
INSERT INTO ref.health_band VALUES
  ('HEALTHY','Healthy',70,false), ('WARNING','Warning',40,false), ('DANGER','Danger',0,false), ('FAULT','Fault',NULL,true)
ON CONFLICT (health_band_code) DO UPDATE SET name = EXCLUDED.name, min_index = EXCLUDED.min_index, is_detected = EXCLUDED.is_detected
  WHERE (ref.health_band.name, ref.health_band.min_index, ref.health_band.is_detected)
        IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.min_index, EXCLUDED.is_detected);

CREATE TABLE IF NOT EXISTS ref.cert_level (
  cert_level_code text PRIMARY KEY,
  name            text NOT NULL UNIQUE,
  level_rank      integer NOT NULL UNIQUE CHECK (level_rank BETWEEN 1 AND 3)
);
CALL util.add_audit('ref.cert_level');
INSERT INTO ref.cert_level VALUES
  ('APPRENTICE','Apprentice',1), ('TECHNICIAN','Technician',2), ('SENIOR','Senior Technician',3)
ON CONFLICT (cert_level_code) DO UPDATE SET name = EXCLUDED.name, level_rank = EXCLUDED.level_rank
  WHERE (ref.cert_level.name, ref.cert_level.level_rank) IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.level_rank);

CREATE TABLE IF NOT EXISTS ref.certification (
  certification_code text PRIMARY KEY,
  name               text NOT NULL UNIQUE,
  issuing_body       text NOT NULL,
  validity_years     integer                -- NULL = does not expire
);
CALL util.add_audit('ref.certification');
INSERT INTO ref.certification VALUES
  ('EPA608', 'EPA Section 608 Universal',         'US EPA',               NULL),
  ('REFRIG', 'Commercial Refrigeration Service',  'RSES',                 3),
  ('HVAC',   'Air Conditioning Service',          'NATE',                 2),
  ('GEN',    'Standby Generator Service',         'Generac',              2),
  ('TAYLOR', 'Soft Serve Equipment Service',      'Taylor',               2)
ON CONFLICT (certification_code) DO UPDATE SET name = EXCLUDED.name, issuing_body = EXCLUDED.issuing_body,
  validity_years = EXCLUDED.validity_years
  WHERE (ref.certification.name, ref.certification.issuing_body, ref.certification.validity_years)
        IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.issuing_body, EXCLUDED.validity_years);

CREATE TABLE IF NOT EXISTS ref.part (
  part_number          text PRIMARY KEY,
  name                 text NOT NULL UNIQUE,
  equipment_class_code text REFERENCES ref.equipment_class,   -- NULL = used across classes
  unit_cost_usd        numeric(8,2) NOT NULL CHECK (unit_cost_usd > 0)
);
CALL util.add_audit('ref.part');
INSERT INTO ref.part VALUES
  ('P-GSK-CLR',   'Walk-in cooler door gasket',            'COOLER',     85.00),
  ('P-GSK-FRZ',   'Walk-in freezer door gasket (heated)',  'FREEZER',   110.00),
  ('P-COIL-CLN',  'Condenser coil cleaner, 1 gal',         NULL,         25.00),
  ('P-EVAP-FAN',  'Evaporator fan motor',                  NULL,        165.00),
  ('P-R404A',     'R-404A refrigerant, 24 lb cylinder',    NULL,        320.00),
  ('P-DEF-TMR',   'Defrost timer',                         'FREEZER',    95.00),
  ('P-DEF-HTR',   'Defrost heater element',                'FREEZER',   140.00),
  ('P-CONTACTOR', 'Compressor contactor',                  NULL,         60.00),
  ('P-START-CAP', 'Compressor start capacitor',            NULL,         35.00),
  ('P-RUN-CAP',   'Condenser fan run capacitor',           'HVAC',       30.00),
  ('P-FILTER',    'HVAC filter 20x25x2, 4-pack',           'HVAC',       48.00),
  ('P-BELT',      'Blower belt',                           'HVAC',       22.00),
  ('P-R410A',     'R-410A refrigerant, 25 lb cylinder',    'HVAC',      290.00),
  ('P-GEN-OIL',   'Generator oil and filter kit',          'GENERATOR',  55.00),
  ('P-GEN-BATT',  'Generator starting battery',            'GENERATOR', 180.00),
  ('P-GEN-AVR',   'Generator automatic voltage regulator', 'GENERATOR', 260.00),
  ('P-TAY-KIT',   'Taylor tune-up kit',                    'SOFTSERVE', 120.00),
  ('P-TAY-BLADE', 'Taylor beater scraper blades',          'SOFTSERVE',  45.00)
ON CONFLICT (part_number) DO UPDATE SET name = EXCLUDED.name, equipment_class_code = EXCLUDED.equipment_class_code,
  unit_cost_usd = EXCLUDED.unit_cost_usd
  WHERE (ref.part.name, ref.part.equipment_class_code, ref.part.unit_cost_usd)
        IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.equipment_class_code, EXCLUDED.unit_cost_usd);

-- The known fix for an undetected (or, for soft serve, detected) condition on a class of equipment.
CREATE TABLE IF NOT EXISTS ref.repair_task (
  repair_task_code     text PRIMARY KEY,
  equipment_class_code text NOT NULL REFERENCES ref.equipment_class,
  health_band_code     text NOT NULL REFERENCES ref.health_band,   -- the condition this task answers
  name                 text NOT NULL UNIQUE,
  symptom              text NOT NULL,
  min_cert_level_code  text NOT NULL REFERENCES ref.cert_level,
  est_minutes          integer NOT NULL CHECK (est_minutes > 0),
  UNIQUE (equipment_class_code, health_band_code)
);
CALL util.add_audit('ref.repair_task');
INSERT INTO ref.repair_task VALUES
  ('CLR-SEAL', 'COOLER',    'WARNING', 'Replace cooler door gasket and clean condenser coil',
     'Box running warm with no fault showing: air leak at the door or a dirty coil', 'APPRENTICE', 45),
  ('CLR-EVAP', 'COOLER',    'DANGER',  'Replace evaporator fan motor and check refrigerant charge',
     'Box well above design temperature; product at risk within hours', 'TECHNICIAN', 90),
  ('FRZ-DEFR', 'FREEZER',   'WARNING', 'Replace defrost timer and heater element',
     'Freezer warming between defrosts with no fault showing', 'TECHNICIAN', 75),
  ('FRZ-COMP', 'FREEZER',   'DANGER',  'Replace compressor contactor and start capacitor, recharge',
     'Freezer far above design temperature; product loss imminent', 'SENIOR', 120),
  ('HVAC-AIR', 'HVAC',      'WARNING', 'Replace filters and blower belt',
     'Supply air running warm with no fault showing: restricted airflow', 'APPRENTICE', 30),
  ('HVAC-CAP', 'HVAC',      'DANGER',  'Replace condenser fan capacitor and recharge',
     'Supply air far above design: condenser not rejecting heat', 'TECHNICIAN', 60),
  ('GEN-SVC',  'GENERATOR', 'WARNING', 'Generator service: oil, filter and starting battery',
     'Exercise runs carrying above-normal load', 'TECHNICIAN', 60),
  ('GEN-AVR',  'GENERATOR', 'DANGER',  'Replace automatic voltage regulator',
     'Exercise runs near full load; unit may not carry the store in an outage', 'SENIOR', 90),
  ('TAY-TUNE', 'SOFTSERVE', 'FAULT',   'Taylor tune-up and scraper blade replacement',
     'Machine down in Needs Service (the ice cream machine is broken)', 'APPRENTICE', 60)
ON CONFLICT (repair_task_code) DO UPDATE SET equipment_class_code = EXCLUDED.equipment_class_code,
  health_band_code = EXCLUDED.health_band_code, name = EXCLUDED.name, symptom = EXCLUDED.symptom,
  min_cert_level_code = EXCLUDED.min_cert_level_code, est_minutes = EXCLUDED.est_minutes
  WHERE (ref.repair_task.equipment_class_code, ref.repair_task.health_band_code, ref.repair_task.name,
         ref.repair_task.symptom, ref.repair_task.min_cert_level_code, ref.repair_task.est_minutes)
        IS DISTINCT FROM (EXCLUDED.equipment_class_code, EXCLUDED.health_band_code, EXCLUDED.name,
         EXCLUDED.symptom, EXCLUDED.min_cert_level_code, EXCLUDED.est_minutes);

-- Certifications a task requires (all of them). PK = TASK|CERT.
CREATE TABLE IF NOT EXISTS ref.repair_task_certification (
  repair_task_certification_id text PRIMARY KEY,
  repair_task_code   text NOT NULL REFERENCES ref.repair_task,
  certification_code text NOT NULL REFERENCES ref.certification,
  CHECK (repair_task_certification_id = repair_task_code || '|' || certification_code)
);
CALL util.add_audit('ref.repair_task_certification');
INSERT INTO ref.repair_task_certification
SELECT t || '|' || c, t, c FROM (VALUES
  ('CLR-EVAP','EPA608'), ('CLR-EVAP','REFRIG'),
  ('FRZ-DEFR','REFRIG'),
  ('FRZ-COMP','EPA608'), ('FRZ-COMP','REFRIG'),
  ('HVAC-CAP','EPA608'), ('HVAC-CAP','HVAC'),
  ('GEN-SVC','GEN'), ('GEN-AVR','GEN'),
  ('TAY-TUNE','TAYLOR')
) v(t, c)
ON CONFLICT (repair_task_certification_id) DO NOTHING;

-- Parts (and quantity) a task consumes. PK = TASK|PART.
CREATE TABLE IF NOT EXISTS ref.repair_task_part (
  repair_task_part_id text PRIMARY KEY,
  repair_task_code    text NOT NULL REFERENCES ref.repair_task,
  part_number         text NOT NULL REFERENCES ref.part,
  quantity            integer NOT NULL CHECK (quantity > 0),
  CHECK (repair_task_part_id = repair_task_code || '|' || part_number)
);
CALL util.add_audit('ref.repair_task_part');
INSERT INTO ref.repair_task_part
SELECT t || '|' || p, t, p, q FROM (VALUES
  ('CLR-SEAL','P-GSK-CLR',1), ('CLR-SEAL','P-COIL-CLN',1),
  ('CLR-EVAP','P-EVAP-FAN',1), ('CLR-EVAP','P-R404A',1),
  ('FRZ-DEFR','P-DEF-TMR',1), ('FRZ-DEFR','P-DEF-HTR',1),
  ('FRZ-COMP','P-CONTACTOR',1), ('FRZ-COMP','P-START-CAP',1), ('FRZ-COMP','P-R404A',1),
  ('HVAC-AIR','P-FILTER',1), ('HVAC-AIR','P-BELT',1),
  ('HVAC-CAP','P-RUN-CAP',1), ('HVAC-CAP','P-R410A',1),
  ('GEN-SVC','P-GEN-OIL',1), ('GEN-SVC','P-GEN-BATT',1),
  ('GEN-AVR','P-GEN-AVR',1),
  ('TAY-TUNE','P-TAY-KIT',1), ('TAY-TUNE','P-TAY-BLADE',1)
) v(t, p, q)
ON CONFLICT (repair_task_part_id) DO UPDATE SET quantity = EXCLUDED.quantity
  WHERE ref.repair_task_part.quantity IS DISTINCT FROM EXCLUDED.quantity;

-- The demo anchor: the date every seeded date was written against. Clock-relative (*_live) views shift seeded dates
-- by (current_date - anchor_date), so the story the data tells (who is expiring soon, what has lapsed) stays the same
-- every day the demo is opened instead of drifting as the calendar moves.
CREATE TABLE IF NOT EXISTS ref.demo_setting (
  demo_setting_id text PRIMARY KEY CHECK (demo_setting_id = 'DEFAULT'),
  anchor_date     date NOT NULL
);
CALL util.add_audit('ref.demo_setting');
INSERT INTO ref.demo_setting VALUES ('DEFAULT', '2026-11-01')
ON CONFLICT (demo_setting_id) DO UPDATE SET anchor_date = EXCLUDED.anchor_date
  WHERE ref.demo_setting.anchor_date IS DISTINCT FROM EXCLUDED.anchor_date;
