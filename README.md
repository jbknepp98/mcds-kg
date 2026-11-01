# McDonald's Arkansas — demo data + Atlas domain

Rebuilt locally from grit's `mcdowells-ops` (store/territory layer), branded McDonald's.

| Piece | Where |
|---|---|
| Postgres DB | `mcdonalds_ar` in container `bible-pg` (localhost:5433). Owner `mcd_admin`, read-only `mcd_reader` (api views only). Passwords in `mcd.env` (gitignored) |
| Schemas | `util` (audit plumbing), `ref` (location_type, operating_status, county, equipment_class), `org` (territory, store), `api` (views Connect polls) |
| Connect | `mcd-pg` = `con_c10edc` (topics `Territories`, `Stores`); `mcd-historian` = `con_faabed` (dataset `McDonalds`, template `con_faabed/McDonalds/[Tag]`) |
| Atlas | library `mcdonalds` (only dependency: atlas-common), domain `mcdonalds-ops`; copies in `atlas/` |

## Rebuild
- DB: `./build.sh` (idempotent; ends with `sql/verify_org.sql`, all rows must say PASS)
- Seed refresh from grit: `tools/grit_cypher.py` export → `seed/stores_grit.csv`, then `tools/grit_store_defs.py` (exact coords from definitions), `tools/gen_org_data.py`
- Connect sources: `tools/connect_setup.py` (matches on alias; PUTs settings — POST ignores settings)
- Atlas maps: `tools/gen_maps.py` → `atlas/maps.json` (submitted via AddInstanceMapDefinitions)

## Every table carries
`created_utc, modified_utc, is_deleted, deleted_utc, row_version` — `row_version` is the watermark (database-wide sequence, set by trigger). Never hard-delete.

## Expected compiled counts
1,153 instances (1 enterprise, 6 territories, 191 stores, 5×191 equipment), 1,152 contains edges, 1,719 bound signals, 764 calculated health properties.
