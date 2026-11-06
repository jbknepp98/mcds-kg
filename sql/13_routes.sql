-- Technician truck routes on real Arkansas roads, and where every truck is at any moment.
--
-- The plan is static data written by tools/plan_routes.py (Valhalla over OpenStreetMap). It is a rotation of
-- fleet.route_setting.rotation_days calendar days anchored on a Monday; a technician with no stops on a day stays
-- parked at their home store. Positions are never stored: fleet.truck_position_at(ts) derives them from the plan,
-- so the demo is right whenever it is opened and any past moment can be replayed.
-- Times of day are Arkansas local time (America/Chicago), so daylight saving is handled by Postgres.
-- Run as mcd_admin. Re-runnable.

CREATE TABLE IF NOT EXISTS fleet.route_setting (
  route_setting_id text PRIMARY KEY CHECK (route_setting_id = 'DEFAULT'),
  anchor_date      date NOT NULL CHECK (extract(isodow FROM anchor_date) = 1),   -- a Monday = rotation day 0
  rotation_days    integer NOT NULL CHECK (rotation_days BETWEEN 7 AND 56 AND rotation_days % 7 = 0),
  time_zone        text NOT NULL,
  planned_utc      timestamptz(0) NOT NULL,
  osm_extract      text NOT NULL                                                 -- road data the plan was routed on
);
CALL util.add_audit('fleet.route_setting');

-- One row per stop. Stop 0 is the start of the day at the home store; the last stop is the return to it.
-- PK = TECH|Dnn|ss.
CREATE TABLE IF NOT EXISTS fleet.route_stop (
  route_stop_id  text PRIMARY KEY,
  technician_id  text NOT NULL REFERENCES hr.technician,
  rotation_day   integer NOT NULL CHECK (rotation_day >= 0),
  stop_seq       integer NOT NULL CHECK (stop_seq >= 0),
  store_id       text NOT NULL REFERENCES org.store,
  stop_kind      text NOT NULL CHECK (stop_kind IN ('START','SERVICE','LUNCH','END')),
  arrive_sec     integer NOT NULL CHECK (arrive_sec BETWEEN 0 AND 86400),       -- seconds after local midnight
  depart_sec     integer NOT NULL CHECK (depart_sec BETWEEN 0 AND 86400),
  CHECK (depart_sec >= arrive_sec),
  CHECK (route_stop_id = technician_id || '|D' || lpad(rotation_day::text, 2, '0') || '|' || lpad(stop_seq::text, 2, '0')),
  UNIQUE (technician_id, rotation_day, stop_seq)
);
CALL util.add_audit('fleet.route_stop');

-- The drive into stop stop_seq from stop stop_seq-1, with its road shape. offset_sec[i] = seconds after leaving
-- when the truck passes (lat[i], lon[i]), spread along each road segment by Valhalla's own maneuver times.
-- PK = TECH|Dnn|ss (same as the stop it arrives at).
CREATE TABLE IF NOT EXISTS fleet.route_leg (
  route_leg_id   text PRIMARY KEY REFERENCES fleet.route_stop (route_stop_id),
  technician_id  text NOT NULL REFERENCES hr.technician,
  rotation_day   integer NOT NULL,
  stop_seq       integer NOT NULL CHECK (stop_seq >= 1),
  from_store_id  text NOT NULL REFERENCES org.store,
  to_store_id    text NOT NULL REFERENCES org.store,
  depart_sec     integer NOT NULL,
  drive_sec      integer NOT NULL CHECK (drive_sec > 0),
  road_miles     numeric(6,1) NOT NULL,
  lat            double precision[] NOT NULL,
  lon            double precision[] NOT NULL,
  offset_sec     integer[] NOT NULL,
  CHECK (cardinality(lat) = cardinality(lon) AND cardinality(lat) = cardinality(offset_sec) AND cardinality(lat) >= 2),
  CHECK (route_leg_id = technician_id || '|D' || lpad(rotation_day::text, 2, '0') || '|' || lpad(stop_seq::text, 2, '0'))
);
CALL util.add_audit('fleet.route_leg');
CREATE INDEX IF NOT EXISTS ix_route_leg_day ON fleet.route_leg (rotation_day, technician_id);
CREATE INDEX IF NOT EXISTS ix_route_stop_day ON fleet.route_stop (rotation_day, technician_id);

CREATE TABLE IF NOT EXISTS ref.truck_status (
  truck_status_code integer PRIMARY KEY,
  name              text NOT NULL
);
CALL util.add_audit('ref.truck_status');
INSERT INTO ref.truck_status VALUES (0, 'Off duty'), (10, 'Driving'), (20, 'On site'), (30, 'Lunch')
ON CONFLICT (truck_status_code) DO UPDATE SET name = EXCLUDED.name WHERE ref.truck_status.name IS DISTINCT FROM EXCLUDED.name;

-- Where every technician's truck is at ts. Deterministic: the same ts always gives the same answer.
CREATE OR REPLACE FUNCTION fleet.truck_position_at(ts timestamptz)
RETURNS TABLE (technician_id text, truck_id text, rotation_day integer, status_code integer, status text,
               latitude double precision, longitude double precision, store_id text, next_store_id text,
               eta_utc timestamptz, as_of_utc timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
WITH s AS (SELECT * FROM fleet.route_setting WHERE route_setting_id = 'DEFAULT' AND NOT is_deleted),
clock AS (
  SELECT (ts AT TIME ZONE s.time_zone)::date AS local_day,
         extract(epoch FROM (ts AT TIME ZONE s.time_zone) - (ts AT TIME ZONE s.time_zone)::date)::double precision AS sec,
         s.time_zone,
         ((((ts AT TIME ZONE s.time_zone)::date - s.anchor_date) % s.rotation_days) + s.rotation_days) % s.rotation_days AS rday
  FROM s),
tech AS (
  SELECT t.technician_id, t.home_store_id, ta.truck_id
  FROM hr.technician t
  LEFT JOIN fleet.truck_assignment ta ON ta.technician_id = t.technician_id AND ta.end_date IS NULL AND NOT ta.is_deleted
  WHERE NOT t.is_deleted),
at_stop AS (
  SELECT rs.technician_id, rs.store_id, rs.stop_kind
  FROM fleet.route_stop rs, clock c
  WHERE rs.rotation_day = c.rday AND NOT rs.is_deleted
    AND rs.stop_kind IN ('SERVICE','LUNCH') AND c.sec >= rs.arrive_sec AND c.sec < rs.depart_sec),
on_leg AS (
  SELECT l.technician_id, l.to_store_id, l.depart_sec, l.drive_sec, c.sec - l.depart_sec AS into_leg,
         l.lat, l.lon, l.offset_sec
  FROM fleet.route_leg l, clock c
  WHERE l.rotation_day = c.rday AND NOT l.is_deleted
    AND c.sec >= l.depart_sec AND c.sec < l.depart_sec + l.drive_sec),
leg_pos AS (   -- interpolate between the two shape points either side of the elapsed time
  SELECT DISTINCT ON (g.technician_id) g.technician_id, g.to_store_id, g.depart_sec, g.drive_sec,
         g.lat[i] + (g.lat[i+1] - g.lat[i]) * f AS lat, g.lon[i] + (g.lon[i+1] - g.lon[i]) * f AS lon
  FROM on_leg g
  CROSS JOIN LATERAL generate_subscripts(g.offset_sec, 1) AS i
  CROSS JOIN LATERAL (SELECT CASE WHEN g.offset_sec[i+1] > g.offset_sec[i]
                                  THEN least(1, greatest(0, (g.into_leg - g.offset_sec[i]) / (g.offset_sec[i+1] - g.offset_sec[i])))
                                  ELSE 0 END AS f) ff
  WHERE i < cardinality(g.offset_sec) AND g.offset_sec[i] <= g.into_leg
  ORDER BY g.technician_id, i DESC),
nxt AS (       -- the next stop still to come today (destination while driving, next job while on site)
  SELECT DISTINCT ON (rs.technician_id) rs.technician_id, rs.store_id, rs.arrive_sec
  FROM fleet.route_stop rs, clock c
  WHERE rs.rotation_day = c.rday AND NOT rs.is_deleted AND rs.arrive_sec > c.sec AND rs.stop_kind IN ('SERVICE','END')
  ORDER BY rs.technician_id, rs.arrive_sec)
SELECT t.technician_id, t.truck_id, c.rday,
       CASE WHEN lp.technician_id IS NOT NULL THEN 10 WHEN a.stop_kind = 'LUNCH' THEN 30
            WHEN a.technician_id IS NOT NULL THEN 20 ELSE 0 END AS status_code,
       CASE WHEN lp.technician_id IS NOT NULL THEN 'Driving' WHEN a.stop_kind = 'LUNCH' THEN 'Lunch'
            WHEN a.technician_id IS NOT NULL THEN 'On site' ELSE 'Off duty' END AS status,
       coalesce(lp.lat, st.latitude::double precision), coalesce(lp.lon, st.longitude::double precision),
       CASE WHEN lp.technician_id IS NULL THEN coalesce(a.store_id, t.home_store_id) END AS store_id,
       CASE WHEN lp.technician_id IS NOT NULL OR a.technician_id IS NOT NULL THEN n.store_id END AS next_store_id,
       CASE WHEN lp.technician_id IS NOT NULL OR a.technician_id IS NOT NULL
            THEN ((c.local_day + make_interval(secs => n.arrive_sec)) AT TIME ZONE c.time_zone) END AS eta_utc,
       ts AS as_of_utc
FROM tech t
CROSS JOIN clock c
LEFT JOIN leg_pos lp ON lp.technician_id = t.technician_id
LEFT JOIN at_stop a ON a.technician_id = t.technician_id
LEFT JOIN nxt n ON n.technician_id = t.technician_id
JOIN org.store st ON st.store_id = coalesce(a.store_id, t.home_store_id)
$$;

-- The path a technician's truck drove between t0 and t1: road points while driving, one point per stop.
-- Capped at 7 days so a careless call cannot return a year of road shape.
CREATE OR REPLACE FUNCTION fleet.truck_track(tech text, t0 timestamptz, t1 timestamptz)
RETURNS TABLE (ts timestamptz, latitude double precision, longitude double precision, status_code integer, store_id text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
WITH s AS (SELECT * FROM fleet.route_setting WHERE route_setting_id = 'DEFAULT' AND NOT is_deleted),
days AS (
  SELECT d::date AS local_day, s.time_zone,
         (((d::date - s.anchor_date) % s.rotation_days) + s.rotation_days) % s.rotation_days AS rday
  FROM s, generate_series((t0 AT TIME ZONE s.time_zone)::date,
                          (least(t1, t0 + interval '7 days') AT TIME ZONE s.time_zone)::date, interval '1 day') d),
pts AS (
  SELECT ((d.local_day + make_interval(secs => l.depart_sec + l.offset_sec[i])) AT TIME ZONE d.time_zone) AS ts,
         l.lat[i] AS latitude, l.lon[i] AS longitude, 10 AS status_code, NULL::text AS store_id
  FROM days d
  JOIN fleet.route_leg l ON l.rotation_day = d.rday AND l.technician_id = tech AND NOT l.is_deleted
  CROSS JOIN LATERAL generate_subscripts(l.offset_sec, 1) i
  WHERE l.offset_sec[i] < l.drive_sec          -- the arrival itself is the stop's point below
  UNION ALL
  SELECT ((d.local_day + make_interval(secs => r.arrive_sec)) AT TIME ZONE d.time_zone),
         st.latitude::double precision, st.longitude::double precision,
         CASE r.stop_kind WHEN 'LUNCH' THEN 30 WHEN 'SERVICE' THEN 20 ELSE 0 END, r.store_id
  FROM days d
  JOIN fleet.route_stop r ON r.rotation_day = d.rday AND r.technician_id = tech AND NOT r.is_deleted
  JOIN org.store st ON st.store_id = r.store_id)
SELECT * FROM pts WHERE ts >= t0 AND ts <= least(t1, t0 + interval '7 days') ORDER BY ts
$$;

-- Clock-relative (reads now()): Connect polls this every minute for the live truck positions.
CREATE OR REPLACE VIEW api.v_truck_position_live AS
SELECT p.technician_id, p.truck_id, p.status_code, p.status, round(p.latitude::numeric, 6)::double precision AS latitude,
       round(p.longitude::numeric, 6)::double precision AS longitude, p.store_id, p.next_store_id, p.eta_utc,
       date_trunc('second', p.as_of_utc) AS as_of_utc
FROM fleet.truck_position_at(now()) p;

-- Clock-relative: each truck's trail over the last 7 days up to now, one row per road point or stop. Connect
-- serves it as a time series (watermark on "Timestamp"), so Atlas UNWIND on the GPS properties returns real history.
CREATE OR REPLACE VIEW api.v_truck_track_recent AS
SELECT k.truck_id, k.current_technician_id AS technician_id, t.ts AS ts_utc, t.latitude, t.longitude, t.status_code,
       t.store_id
FROM api.v_truck k
CROSS JOIN LATERAL fleet.truck_track(k.current_technician_id, now() - interval '7 days', now()) t
WHERE k.current_technician_id IS NOT NULL;

-- The day's plan, readable (clock-free).
CREATE OR REPLACE VIEW api.v_route_stop AS
SELECT rs.route_stop_id, rs.technician_id, rs.rotation_day, rs.stop_seq, rs.store_id, rs.stop_kind,
       to_char(make_interval(secs => rs.arrive_sec), 'HH24:MI') AS arrive_local,
       to_char(make_interval(secs => rs.depart_sec), 'HH24:MI') AS depart_local,
       l.road_miles, round(l.drive_sec / 60.0)::integer AS drive_minutes, rs.modified_utc, rs.row_version
FROM fleet.route_stop rs
LEFT JOIN fleet.route_leg l ON l.route_leg_id = rs.route_stop_id AND NOT l.is_deleted
WHERE NOT rs.is_deleted;

-- The functions run as their owner, so the reader needs only the api views and EXECUTE.
REVOKE ALL ON FUNCTION fleet.truck_position_at(timestamptz), fleet.truck_track(text, timestamptz, timestamptz) FROM PUBLIC;
GRANT USAGE ON SCHEMA fleet TO mcd_reader;
GRANT EXECUTE ON FUNCTION fleet.truck_position_at(timestamptz), fleet.truck_track(text, timestamptz, timestamptz) TO mcd_reader;
GRANT SELECT ON api.v_truck_position_live, api.v_truck_track_recent, api.v_route_stop TO mcd_reader;
