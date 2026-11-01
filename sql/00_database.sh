#!/bin/bash
# Creates roles + database inside the bible-pg container. Run from repo root. Idempotent.
set -euo pipefail
source "$(dirname "$0")/../mcd.env"
PSQL="docker exec -i bible-pg psql -v ON_ERROR_STOP=1 -U bible_admin -d postgres"
$PSQL -v apw="$MCD_ADMIN_PASSWORD" -v rpw="$MCD_READER_PASSWORD" <<'SQL'
SELECT 'CREATE ROLE mcd_admin LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='mcd_admin') \gexec
SELECT 'CREATE ROLE mcd_reader LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='mcd_reader') \gexec
ALTER ROLE mcd_admin PASSWORD :'apw';
ALTER ROLE mcd_reader PASSWORD :'rpw';
SELECT 'CREATE DATABASE mcdonalds_ar OWNER mcd_admin' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='mcdonalds_ar') \gexec
REVOKE ALL ON DATABASE mcdonalds_ar FROM PUBLIC;
GRANT CONNECT ON DATABASE mcdonalds_ar TO mcd_admin, mcd_reader;
SQL
