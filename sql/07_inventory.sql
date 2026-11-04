-- 30 days of daily truck counts ending at the demo anchor (2026-11-01). Re-runnable: each date
-- upserts only what changed. Later days are added by tools/health_baseline.py (CALL fleet.generate_inventory(current_date)).
CALL fleet.generate_inventory_range('2026-10-03', '2026-11-01');
