-- Soft serve: "the ice cream machine is broken" layer. Run as mcd_admin after 06/09. Re-runnable.

-- What an hour of a down machine costs: ~12 treats an hour at ~$3.49 (McFlurry / cone / sundae mix).
ALTER TABLE ref.equipment_class ADD COLUMN IF NOT EXISTS downtime_revenue_per_hour_usd numeric(7,2);
UPDATE ref.equipment_class SET downtime_revenue_per_hour_usd = 42.00
WHERE equipment_class_code = 'SOFTSERVE' AND downtime_revenue_per_hour_usd IS DISTINCT FROM 42.00;

-- Right to Repair storyline: Cody Whitfield (TECH-003) has NOT taken the Taylor course yet (booked for Dec 2026);
-- his certificate row was issued in error and is withdrawn. Without the 2024 repair exemption he may not touch the
-- machine; with it (detour query $rightToRepair = true) he can, because every truck carries the Taylor parts.
UPDATE hr.technician_certification SET is_deleted = true
WHERE technician_certification_id = 'TECH-003|TAYLOR' AND NOT is_deleted;

-- Taylor certification is scarce: the company only paid for Taylor's authorised-service course for three
-- technicians (Darnell Brooks, Little Rock; Tyrone Banks, Blytheville; Ana Delgado, Fort Smith). The other
-- certificates in the seed were never valid and are withdrawn. This is what makes Right to Repair matter.
UPDATE hr.technician_certification SET is_deleted = true
WHERE certification_code = 'TAYLOR' AND technician_id NOT IN ('TECH-001', 'TECH-008', 'TECH-011') AND NOT is_deleted;
