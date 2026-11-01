-- Schemas + shared audit plumbing (Postgres analogue of rowversion). Run as mcd_admin.
CREATE SCHEMA IF NOT EXISTS util;
CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS org;
CREATE SCHEMA IF NOT EXISTS api;

-- One database-wide monotonic counter = the watermark for every table.
CREATE SEQUENCE IF NOT EXISTS util.row_version_seq;

CREATE OR REPLACE FUNCTION util.audit_row() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.row_version := nextval('util.row_version_seq');
  IF TG_OP = 'INSERT' THEN
    NEW.created_utc  := COALESCE(NEW.created_utc, now());
    NEW.modified_utc := NEW.created_utc;
  ELSE
    NEW.created_utc  := OLD.created_utc;
    NEW.modified_utc := now();
  END IF;
  IF NEW.is_deleted AND NEW.deleted_utc IS NULL THEN NEW.deleted_utc := now(); END IF;
  IF NOT NEW.is_deleted THEN NEW.deleted_utc := NULL; END IF;
  RETURN NEW;
END $$;

-- Adds the five audit columns + trigger to a table. Safe to re-run.
CREATE OR REPLACE PROCEDURE util.add_audit(tbl regclass) LANGUAGE plpgsql AS $$
BEGIN
  EXECUTE format('ALTER TABLE %s
     ADD COLUMN IF NOT EXISTS created_utc  timestamptz(3) NOT NULL DEFAULT now(),
     ADD COLUMN IF NOT EXISTS modified_utc timestamptz(3) NOT NULL DEFAULT now(),
     ADD COLUMN IF NOT EXISTS is_deleted   boolean NOT NULL DEFAULT false,
     ADD COLUMN IF NOT EXISTS deleted_utc  timestamptz(3),
     ADD COLUMN IF NOT EXISTS row_version  bigint NOT NULL DEFAULT 0', tbl);
  EXECUTE format('DROP TRIGGER IF EXISTS trg_audit ON %s', tbl);
  EXECUTE format('CREATE TRIGGER trg_audit BEFORE INSERT OR UPDATE ON %s FOR EACH ROW EXECUTE FUNCTION util.audit_row()', tbl);
  EXECUTE format('CREATE UNIQUE INDEX IF NOT EXISTS %I ON %s (row_version)', 'ux_' || replace(tbl::text,'.','_') || '_rv', tbl);
END $$;
