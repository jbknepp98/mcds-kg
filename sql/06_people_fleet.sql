-- Technicians, certifications, trucks, assignments, par levels. Run as mcd_admin. Re-runnable.
CREATE SCHEMA IF NOT EXISTS hr;
CREATE SCHEMA IF NOT EXISTS fleet;

CREATE TABLE IF NOT EXISTS hr.technician (
  technician_id     text PRIMARY KEY CHECK (technician_id ~ '^TECH-[0-9]{3}$'),
  first_name        text NOT NULL,
  last_name         text NOT NULL,
  cert_level_code   text NOT NULL REFERENCES ref.cert_level,
  home_territory_id text NOT NULL REFERENCES org.territory,
  home_store_id     text NOT NULL REFERENCES org.store,      -- where the day starts by default
  phone             text NOT NULL,
  hire_date         date NOT NULL
);
CALL util.add_audit('hr.technician');

-- PK = TECH|CERT. expires_date NULL = never expires (EPA 608).
CREATE TABLE IF NOT EXISTS hr.technician_certification (
  technician_certification_id text PRIMARY KEY,
  technician_id      text NOT NULL REFERENCES hr.technician,
  certification_code text NOT NULL REFERENCES ref.certification,
  certificate_number text NOT NULL UNIQUE,
  issued_date        date NOT NULL,
  expires_date       date,
  CHECK (technician_certification_id = technician_id || '|' || certification_code),
  CHECK (expires_date IS NULL OR expires_date > issued_date)
);
CALL util.add_audit('hr.technician_certification');

CREATE TABLE IF NOT EXISTS fleet.truck (
  truck_id          text PRIMARY KEY CHECK (truck_id ~ '^TRK-[0-9]{3}$'),
  make              text NOT NULL,
  model             text NOT NULL,
  model_year        integer NOT NULL CHECK (model_year BETWEEN 2015 AND 2027),
  license_plate     text NOT NULL UNIQUE,
  home_territory_id text NOT NULL REFERENCES org.territory
);
CALL util.add_audit('fleet.truck');

-- Effective-dated; end_date NULL = current. PK = TRUCK|TECH|yyyy-mm-dd(start).
CREATE TABLE IF NOT EXISTS fleet.truck_assignment (
  truck_assignment_id text PRIMARY KEY,
  truck_id      text NOT NULL REFERENCES fleet.truck,
  technician_id text NOT NULL REFERENCES hr.technician,
  start_date    date NOT NULL,
  end_date      date,
  CHECK (truck_assignment_id = truck_id || '|' || technician_id || '|' || to_char(start_date, 'YYYY-MM-DD')),
  CHECK (end_date IS NULL OR end_date >= start_date)
);
CALL util.add_audit('fleet.truck_assignment');
CREATE UNIQUE INDEX IF NOT EXISTS ux_truck_assignment_current_truck ON fleet.truck_assignment (truck_id) WHERE end_date IS NULL AND NOT is_deleted;
CREATE UNIQUE INDEX IF NOT EXISTS ux_truck_assignment_current_tech  ON fleet.truck_assignment (technician_id) WHERE end_date IS NULL AND NOT is_deleted;

-- Stocking plan: what each truck should carry after a restock. par_quantity 0 = deliberately not carried.
-- PK = TRUCK|PART.
CREATE TABLE IF NOT EXISTS fleet.truck_par_level (
  truck_par_level_id text PRIMARY KEY,
  truck_id     text NOT NULL REFERENCES fleet.truck,
  part_number  text NOT NULL REFERENCES ref.part,
  par_quantity integer NOT NULL CHECK (par_quantity >= 0),
  CHECK (truck_par_level_id = truck_id || '|' || part_number)
);
CALL util.add_audit('fleet.truck_par_level');

-- Daily count of every part on every truck. PK = TRUCK|yyyymmdd|PART.
CREATE TABLE IF NOT EXISTS fleet.truck_inventory_daily (
  truck_inventory_id text PRIMARY KEY,
  truck_id         text NOT NULL REFERENCES fleet.truck,
  inventory_date   date NOT NULL,
  part_number      text NOT NULL REFERENCES ref.part,
  quantity_on_hand integer NOT NULL CHECK (quantity_on_hand >= 0),
  par_quantity     integer NOT NULL CHECK (par_quantity >= 0),
  counted_by       text REFERENCES hr.technician,
  is_restock_day   boolean NOT NULL,
  CHECK (truck_inventory_id = truck_id || '|' || to_char(inventory_date, 'YYYYMMDD') || '|' || part_number)
);
CALL util.add_audit('fleet.truck_inventory_daily');
CREATE INDEX IF NOT EXISTS ix_truck_inventory_date ON fleet.truck_inventory_daily (truck_id, inventory_date);

-- Generates one day's count for every truck from its par levels and the previous day's count.
-- Restock to par on Mondays and Thursdays; otherwise a part is used up at random (~1 use / 12 days),
-- deterministic per truck/part/date so a rebuild reproduces the same numbers. Idempotent per date.
CREATE OR REPLACE PROCEDURE fleet.generate_inventory(p_date date) LANGUAGE sql AS $$
  INSERT INTO fleet.truck_inventory_daily
    (truck_inventory_id, truck_id, inventory_date, part_number, quantity_on_hand, par_quantity, counted_by, is_restock_day)
  SELECT pl.truck_id || '|' || to_char(p_date, 'YYYYMMDD') || '|' || pl.part_number,
         pl.truck_id, p_date, pl.part_number,
         greatest(0, CASE WHEN restock OR prev.quantity_on_hand IS NULL THEN pl.par_quantity
                          ELSE prev.quantity_on_hand END
                     - CASE WHEN abs(hashtext(pl.truck_id || pl.part_number || p_date::text)) % 12 = 0 THEN 1 ELSE 0 END),
         pl.par_quantity, ta.technician_id, restock
  FROM fleet.truck_par_level pl
  CROSS JOIN LATERAL (SELECT extract(isodow FROM p_date) IN (1, 4) AS restock) r
  LEFT JOIN fleet.truck_inventory_daily prev
         ON prev.truck_id = pl.truck_id AND prev.part_number = pl.part_number AND prev.inventory_date = p_date - 1
  LEFT JOIN fleet.truck_assignment ta
         ON ta.truck_id = pl.truck_id AND NOT ta.is_deleted
        AND p_date >= ta.start_date AND (ta.end_date IS NULL OR p_date <= ta.end_date)
  WHERE NOT pl.is_deleted
  ON CONFLICT (truck_inventory_id) DO UPDATE SET
    quantity_on_hand = EXCLUDED.quantity_on_hand, par_quantity = EXCLUDED.par_quantity,
    counted_by = EXCLUDED.counted_by, is_restock_day = EXCLUDED.is_restock_day
  WHERE (fleet.truck_inventory_daily.quantity_on_hand, fleet.truck_inventory_daily.par_quantity,
         fleet.truck_inventory_daily.counted_by, fleet.truck_inventory_daily.is_restock_day)
        IS DISTINCT FROM (EXCLUDED.quantity_on_hand, EXCLUDED.par_quantity, EXCLUDED.counted_by, EXCLUDED.is_restock_day);
$$;

-- Fills every date from p_from to p_to in order (each day builds on the previous one).
CREATE OR REPLACE PROCEDURE fleet.generate_inventory_range(p_from date, p_to date) LANGUAGE plpgsql AS $$
DECLARE d date := p_from;
BEGIN
  WHILE d <= p_to LOOP
    CALL fleet.generate_inventory(d);
    d := d + 1;
  END LOOP;
END $$;
