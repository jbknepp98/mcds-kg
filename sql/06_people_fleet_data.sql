-- Seed: 18 technicians (Senior / Technician / Apprentice per territory), their certifications,
-- 18 trucks, assignments (with history) and par levels. Run as mcd_admin. Re-runnable.

INSERT INTO hr.technician VALUES
  ('TECH-001','Darnell','Brooks',   'SENIOR',    'territory-central-arkansas',       'AR-20031','501-555-0101','2012-04-16'),
  ('TECH-002','Priya',  'Raman',    'TECHNICIAN','territory-central-arkansas',       'AR-20067','501-555-0102','2019-08-05'),
  ('TECH-003','Cody',   'Whitfield','APPRENTICE','territory-central-arkansas',       'AR-20093','501-555-0103','2025-08-04'),
  ('TECH-004','Ray',    'Tillman',  'SENIOR',    'territory-north-central-arkansas', 'AR-20025','870-555-0104','2010-03-01'),
  ('TECH-005','Hannah', 'Cole',     'TECHNICIAN','territory-north-central-arkansas', 'AR-20027','501-555-0105','2020-01-13'),
  ('TECH-006','Luis',   'Ortega',   'APPRENTICE','territory-north-central-arkansas', 'AR-20077','501-555-0106','2025-02-17'),
  ('TECH-007','Monica', 'Hale',     'SENIOR',    'territory-northeast-arkansas',     'AR-20164','870-555-0107','2013-06-10'),
  ('TECH-008','Tyrone', 'Banks',    'TECHNICIAN','territory-northeast-arkansas',     'AR-20022','870-555-0108','2018-11-26'),
  ('TECH-009','Kaylee', 'Dunn',     'APPRENTICE','territory-northeast-arkansas',     'AR-20090','870-555-0109','2025-05-12'),
  ('TECH-010','Greg',   'Holloway', 'SENIOR',    'territory-northwest-arkansas',     'AR-20075','479-555-0110','2011-09-19'),
  ('TECH-011','Ana',    'Delgado',  'TECHNICIAN','territory-northwest-arkansas',     'AR-20036','479-555-0111','2021-03-08'),
  ('TECH-012','Brandon','Pike',     'APPRENTICE','territory-northwest-arkansas',     'AR-20083','479-555-0112','2024-10-21'),
  ('TECH-013','Curtis', 'Webb',     'SENIOR',    'territory-southeast-arkansas',     'AR-20135','870-555-0113','2009-07-27'),
  ('TECH-014','Jasmine','Ford',     'TECHNICIAN','territory-southeast-arkansas',     'AR-20011','870-555-0114','2020-06-01'),
  ('TECH-015','Ethan',  'Marsh',    'APPRENTICE','territory-southeast-arkansas',     'AR-20146','501-555-0115','2025-01-06'),
  ('TECH-016','Rhonda', 'Pruitt',   'SENIOR',    'territory-southwest-arkansas',     'AR-20043','501-555-0116','2014-02-03'),
  ('TECH-017','Victor', 'Nguyen',   'TECHNICIAN','territory-southwest-arkansas',     'AR-20091','479-555-0117','2019-04-22'),
  ('TECH-018','Molly',  'Grant',    'APPRENTICE','territory-southwest-arkansas',     'AR-20062','870-555-0118','2025-09-15')
ON CONFLICT (technician_id) DO UPDATE SET first_name = EXCLUDED.first_name, last_name = EXCLUDED.last_name,
  cert_level_code = EXCLUDED.cert_level_code, home_territory_id = EXCLUDED.home_territory_id,
  home_store_id = EXCLUDED.home_store_id, phone = EXCLUDED.phone, hire_date = EXCLUDED.hire_date
  WHERE (hr.technician.first_name, hr.technician.last_name, hr.technician.cert_level_code, hr.technician.home_territory_id,
         hr.technician.home_store_id, hr.technician.phone, hr.technician.hire_date)
        IS DISTINCT FROM (EXCLUDED.first_name, EXCLUDED.last_name, EXCLUDED.cert_level_code, EXCLUDED.home_territory_id,
         EXCLUDED.home_store_id, EXCLUDED.phone, EXCLUDED.hire_date);

-- Certifications. expires_date = issued + validity_years (NULL for EPA 608).
-- Story: TECH-002 Priya Raman's Generac certification lapsed 2026-09-15 - she still carries generator parts.
INSERT INTO hr.technician_certification
SELECT v.t || '|' || v.c, v.t, v.c, v.num, v.issued,
       CASE WHEN c.validity_years IS NULL THEN NULL ELSE (v.issued + make_interval(years => c.validity_years))::date END
FROM (VALUES
  ('TECH-001','EPA608','608-U-4471902','2012-09-14'::date), ('TECH-001','REFRIG','RSES-CR-30117','2024-03-11'),
  ('TECH-001','HVAC',  'NATE-AC-88213','2025-02-20'),       ('TECH-001','GEN',   'GNRC-ST-55102','2025-05-06'),
  ('TECH-001','TAYLOR','TAY-SS-10044', '2025-01-15'),
  ('TECH-002','EPA608','608-U-5930218','2019-11-04'),       ('TECH-002','REFRIG','RSES-CR-41290','2024-06-17'),
  ('TECH-002','GEN',   'GNRC-ST-60433','2024-09-15'),       ('TECH-002','TAYLOR','TAY-SS-10291', '2025-04-02'),
  ('TECH-003','TAYLOR','TAY-SS-10877', '2025-10-06'),
  ('TECH-004','EPA608','608-U-3820551','2010-06-21'),       ('TECH-004','REFRIG','RSES-CR-29984','2024-01-29'),
  ('TECH-004','HVAC',  'NATE-AC-87150','2025-03-03'),       ('TECH-004','GEN',   'GNRC-ST-54871','2025-04-14'),
  ('TECH-005','EPA608','608-U-6012774','2020-05-18'),       ('TECH-005','REFRIG','RSES-CR-42015','2024-08-12'),
  ('TECH-005','TAYLOR','TAY-SS-10322', '2025-05-19'),
  ('TECH-006','TAYLOR','TAY-SS-10650', '2025-06-23'),
  ('TECH-007','EPA608','608-U-4630087','2013-10-02'),       ('TECH-007','REFRIG','RSES-CR-30562','2024-04-08'),
  ('TECH-007','HVAC',  'NATE-AC-88540','2025-01-27'),       ('TECH-007','GEN',   'GNRC-ST-55388','2025-06-09'),
  ('TECH-008','EPA608','608-U-5781640','2019-02-11'),       ('TECH-008','REFRIG','RSES-CR-40877','2023-12-04'),
  ('TECH-008','HVAC',  'NATE-AC-89012','2025-07-14'),       ('TECH-008','TAYLOR','TAY-SS-10405', '2025-03-24'),
  ('TECH-009','TAYLOR','TAY-SS-10712', '2025-08-18'),
  ('TECH-010','EPA608','608-U-4102336','2011-12-05'),       ('TECH-010','REFRIG','RSES-CR-30001','2024-02-19'),
  ('TECH-010','HVAC',  'NATE-AC-87633','2025-04-07'),       ('TECH-010','GEN',   'GNRC-ST-55020','2025-03-17'),
  ('TECH-010','TAYLOR','TAY-SS-10118', '2025-02-10'),
  ('TECH-011','EPA608','608-U-6240913','2021-07-26'),       ('TECH-011','REFRIG','RSES-CR-43108','2025-01-13'),
  ('TECH-011','TAYLOR','TAY-SS-10533', '2025-07-07'),
  ('TECH-012','TAYLOR','TAY-SS-10198', '2025-01-20'),
  ('TECH-013','EPA608','608-U-3511470','2009-11-16'),       ('TECH-013','REFRIG','RSES-CR-29702','2023-11-06'),
  ('TECH-013','HVAC',  'NATE-AC-86990','2024-12-09'),       ('TECH-013','GEN',   'GNRC-ST-54630','2025-02-24'),
  ('TECH-014','EPA608','608-U-6105528','2020-09-28'),       ('TECH-014','REFRIG','RSES-CR-42550','2024-10-21'),
  ('TECH-014','TAYLOR','TAY-SS-10367', '2025-04-28'),
  ('TECH-015','TAYLOR','TAY-SS-10480', '2025-03-10'),
  ('TECH-016','EPA608','608-U-4835106','2014-05-12'),       ('TECH-016','REFRIG','RSES-CR-31244','2024-05-20'),
  ('TECH-016','HVAC',  'NATE-AC-88871','2025-05-26'),       ('TECH-016','GEN',   'GNRC-ST-55745','2025-08-04'),
  ('TECH-017','EPA608','608-U-5874419','2019-08-19'),       ('TECH-017','REFRIG','RSES-CR-41733','2024-07-15'),
  ('TECH-017','HVAC',  'NATE-AC-89305','2025-09-08'),       ('TECH-017','TAYLOR','TAY-SS-10599', '2025-06-16'),
  ('TECH-018','TAYLOR','TAY-SS-10930', '2025-10-27')
) v(t, c, num, issued)
JOIN ref.certification c ON c.certification_code = v.c
ON CONFLICT (technician_certification_id) DO UPDATE SET certificate_number = EXCLUDED.certificate_number,
  issued_date = EXCLUDED.issued_date, expires_date = EXCLUDED.expires_date
  WHERE (hr.technician_certification.certificate_number, hr.technician_certification.issued_date, hr.technician_certification.expires_date)
        IS DISTINCT FROM (EXCLUDED.certificate_number, EXCLUDED.issued_date, EXCLUDED.expires_date);

INSERT INTO fleet.truck
SELECT 'TRK-' || lpad((100 + n)::text, 3, '0'), mk, mdl, yr, plate, t.home_territory_id
FROM (VALUES
  ( 1,'Ford','Transit 250',2025,'AR 418 KTB'), ( 2,'Ford','Transit 250',2023,'AR 627 JPW'),
  ( 3,'Ram','ProMaster 2500',2021,'AR 905 HCR'), ( 4,'Ford','Transit 250',2024,'AR 311 KDM'),
  ( 5,'Ram','ProMaster 2500',2022,'AR 774 HXL'), ( 6,'Chevrolet','Express 2500',2020,'AR 258 GVA'),
  ( 7,'Ford','Transit 250',2025,'AR 562 KRS'), ( 8,'Ford','Transit 250',2023,'AR 149 JLN'),
  ( 9,'Chevrolet','Express 2500',2021,'AR 683 HBE'), (10,'Ford','Transit 250',2024,'AR 037 KFY'),
  (11,'Ram','ProMaster 2500',2023,'AR 820 JTC'), (12,'Chevrolet','Express 2500',2020,'AR 476 GQH'),
  (13,'Ford','Transit 250',2024,'AR 391 KMP'), (14,'Ram','ProMaster 2500',2022,'AR 715 HZD'),
  (15,'Chevrolet','Express 2500',2021,'AR 954 HJK'), (16,'Ford','Transit 250',2025,'AR 208 KWA'),
  (17,'Ram','ProMaster 2500',2023,'AR 663 JVR'), (18,'Chevrolet','Express 2500',2019,'AR 530 FSN')
) v(n, mk, mdl, yr, plate)
JOIN hr.technician t ON t.technician_id = 'TECH-' || lpad(n::text, 3, '0')
ON CONFLICT (truck_id) DO UPDATE SET make = EXCLUDED.make, model = EXCLUDED.model, model_year = EXCLUDED.model_year,
  license_plate = EXCLUDED.license_plate, home_territory_id = EXCLUDED.home_territory_id
  WHERE (fleet.truck.make, fleet.truck.model, fleet.truck.model_year, fleet.truck.license_plate, fleet.truck.home_territory_id)
        IS DISTINCT FROM (EXCLUDED.make, EXCLUDED.model, EXCLUDED.model_year, EXCLUDED.license_plate, EXCLUDED.home_territory_id);

-- Assignments: TRK-1nn -> TECH-0nn. History: TRK-103 was Darnell Brooks's van until his new
-- TRK-101 arrived in June 2025; Cody Whitfield inherited it when he was hired.
INSERT INTO fleet.truck_assignment
SELECT truck || '|' || tech || '|' || to_char(s, 'YYYY-MM-DD'), truck, tech, s, e
FROM (
  SELECT 'TRK-' || lpad((100 + n)::text, 3, '0') AS truck, 'TECH-' || lpad(n::text, 3, '0') AS tech,
         CASE n WHEN 1 THEN '2025-06-02'::date WHEN 3 THEN '2025-08-04'::date
                ELSE greatest(t.hire_date, make_date(f.model_year - 1, 10, 1)) END AS s, NULL::date AS e
  FROM generate_series(1, 18) n
  JOIN hr.technician t ON t.technician_id = 'TECH-' || lpad(n::text, 3, '0')
  JOIN fleet.truck f ON f.truck_id = 'TRK-' || lpad((100 + n)::text, 3, '0')
  UNION ALL SELECT 'TRK-103', 'TECH-001', '2020-10-05', '2025-05-30'
) a(truck, tech, s, e)
ON CONFLICT (truck_assignment_id) DO UPDATE SET end_date = EXCLUDED.end_date
  WHERE fleet.truck_assignment.end_date IS DISTINCT FROM EXCLUDED.end_date;

-- Par levels follow the assigned technician's level and certifications (lapsed ones included: the
-- parts stay on the van). TRK-103 deliberately carries no cooler door gasket.
INSERT INTO fleet.truck_par_level
SELECT truck_id || '|' || part_number, truck_id, part_number, max(par)
FROM (
  SELECT ta.truck_id, p.part_number,
         CASE WHEN ta.truck_id = 'TRK-103' AND p.part_number = 'P-GSK-CLR' THEN 0 ELSE p.par END AS par
  FROM fleet.truck_assignment ta
  JOIN hr.technician t ON t.technician_id = ta.technician_id
  CROSS JOIN LATERAL (VALUES
    -- everyone: consumables for the level-1 tasks
    ('P-COIL-CLN', 2, NULL::text, NULL::text), ('P-FILTER', 3, NULL, NULL), ('P-BELT', 2, NULL, NULL),
    ('P-GSK-CLR', 1, NULL, NULL),
    ('P-GSK-FRZ', 1, 'REFRIG', NULL), ('P-DEF-TMR', 1, 'REFRIG', NULL), ('P-DEF-HTR', 1, 'REFRIG', NULL),
    ('P-EVAP-FAN', 1, 'REFRIG', NULL),
    ('P-R404A', 1, 'EPA608', NULL), ('P-CONTACTOR', 1, 'EPA608', NULL), ('P-START-CAP', 1, 'EPA608', NULL),
    ('P-R410A', 1, 'EPA608', NULL), ('P-RUN-CAP', 2, 'EPA608', NULL),
    ('P-GEN-OIL', 2, 'GEN', NULL), ('P-GEN-BATT', 1, 'GEN', NULL), ('P-GEN-AVR', 1, 'GEN', 'SENIOR'),
    -- Taylor parts ride on every van (the parts were never the problem - the service lockout was)
    ('P-TAY-KIT', 1, NULL, NULL), ('P-TAY-BLADE', 2, NULL, NULL)
  ) p(part_number, par, needs_cert, needs_level)
  WHERE ta.end_date IS NULL AND NOT ta.is_deleted
    AND (p.needs_cert IS NULL OR EXISTS (SELECT 1 FROM hr.technician_certification tc
           WHERE tc.technician_id = t.technician_id AND tc.certification_code = p.needs_cert AND NOT tc.is_deleted))
    AND (p.needs_level IS NULL OR t.cert_level_code = p.needs_level)
) x
GROUP BY truck_id, part_number
ON CONFLICT (truck_par_level_id) DO UPDATE SET par_quantity = EXCLUDED.par_quantity
  WHERE fleet.truck_par_level.par_quantity IS DISTINCT FROM EXCLUDED.par_quantity;
