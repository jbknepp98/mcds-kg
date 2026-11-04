#!/bin/bash
# Build/refresh mcdonalds_ar inside bible-pg. Every step is idempotent; safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"
bash sql/00_database.sh
PSQL="docker exec -i bible-pg psql -v ON_ERROR_STOP=1 -q -U bible_admin -d mcdonalds_ar"
for f in 01_infra 02_ref 03_org 03_org_data 04_api_views 05_ref_service 06_people_fleet 06_people_fleet_data 08_geo 10_geo_zip 10_geo_zip_data 11_softserve 07_inventory 09_api_views_service 12_api_views_softserve; do
  echo "== $f"; { echo "SET ROLE mcd_admin;"; cat "sql/$f.sql"; } | $PSQL
done
echo "== verify"; $PSQL -A -F' | ' < sql/verify_org.sql
echo "== verify service"; $PSQL -A -F' | ' < sql/verify_service.sql
