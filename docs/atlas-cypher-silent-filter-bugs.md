# Atlas Cypher: filters silently dropped (wrong rows, no error)

**Build:** `timebase/atlas:2.0-gc4` (Timebase.Atlas 2.0.0), local Docker stack.
**Domain:** `mcdonalds-ops` (191 `Store`, 18 `Technician`, 955 equipment instances). Every technician has exactly
one `basedAt` edge to a store; no technician is based at `AR-20086`.
**Endpoint:** `POST /api/v1/branches/main/domains/mcdonalds-ops/queries`. Same results through the MCP
`ExecuteCypherQuery` tool and from Gage.
**Re-verified:** 2026-11-03.

## Summary

Three standard Cypher constructs parse and run, but their filter is discarded. A dropped filter always
**widens** the result, so the query returns plausible rows that are wrong, and nothing reports a problem.
Unsupported functions (trig, `^`, nested `collect`) fail loudly. These three don't.

| # | Query | Expected | Actual |
|---|---|---|---|
| A1 | `MATCH (s:Store {StoreId: 'AR-20086'}) RETURN count(s)` | 1 | **191** |
| A2 | `MATCH (s:Store) WHERE s.StoreId = 'AR-20086' RETURN count(s)` | 1 | 1 ✔ |
| A3 | `MATCH (t:Technician)-[:basedAt]->(s:Store {StoreId: 'AR-20086'}) RETURN count(t)` | 0 | **18** |
| A4 | `MATCH (t:Technician)-[:basedAt]->(s:Store) WHERE s.StoreId = 'AR-20086' RETURN count(t)` | 0 | 0 ✔ |
| B1 | `MATCH (s:Store) WHERE s.StoreId = 'AR-20086' WITH s MATCH (t:Technician)-[:basedAt]->(s) RETURN count(t), count(DISTINCT s.StoreId)` | 0, 0 | **18, 18** |
| B2 | `MATCH (s:Store), (t:Technician)-[:basedAt]->(s) WHERE s.StoreId = 'AR-20086' RETURN count(t)` | 0 | 0 ✔ |
| C1 | `MATCH (s:Store)-[:contains]->(m:SoftServeMachine) WHERE s.StoreId = 'AR-20086' RETURN collect(m.EquipmentClassCode)` | `['SOFTSERVE']` | **`['COOLER','FREEZER','HVAC','GENERATOR','SOFTSERVE']`** |
| C2 | `MATCH (m:SoftServeMachine) RETURN count(m)` | 191 | 191 ✔ |
| D | `MATCH (t:Technician) MATCH (h:Store {StoreId: t.HomeStoreId}) RETURN count(*), count(DISTINCT h.StoreId)` | 18, 18 | **3438, 191** |
| D2 | `MATCH (t:Technician) MATCH (h:Store) WHERE h.StoreId = t.HomeStoreId RETURN count(*), count(DISTINCT h.StoreId)` | 18, 18 | 18, 18 ✔ |

## The three defects

1. **Inline property maps in a node pattern are ignored** (A1, A3, D). `(n:Label {prop: value})` behaves like
   `(n:Label)`, whether the value is a literal or a reference to an earlier variable. The same filter written in
   `WHERE` works (A2, A4, D2).
2. **A node variable carried through `WITH` is re-bound by a later `MATCH`, not joined** (B1). The second
   `MATCH` treats `s` as a new variable, so every technician comes back paired with their own home store. If both
   patterns share the variable inside one `MATCH`, the join works (B2).
3. **A label on the end node of a relationship pattern is ignored** (C1). On a standalone node pattern the label
   filters correctly (C2).

## Real-world impact

Gage answered "which technicians are within 50 miles of 201 S. Walton Blvd, Bentonville?" with *all 18
technicians are based at 201 S. Walton Blvd*. Its query had the shape of D. Atlas paired each technician with
all 191 stores, and Gage's own distance filter (from Walton's coordinates) then kept only the Bentonville store
rows. So every technician appeared to live there. The correct answer is 3 technicians: Rogers 4.3 mi,
Fayetteville 26.3 mi and Fort Smith 91.4 mi road distance. Gage didn't notice that 18 identical home addresses
was implausible.

These constructs are idiomatic Cypher. A model or a Neo4j user writes them by default, so this will keep
happening in every domain, not just this one.

## Requested fix (any of these, best first)

1. Implement them: inline maps as equality predicates, `WITH`-carried node variables as bound in later
   patterns, and labels on every node of a path.
2. Until then, **reject** them with a parse or plan error that names the construct, e.g. "inline property maps
   are not supported; use WHERE". An error makes Gage rewrite the query. A silent drop makes it report the wrong
   answer.
3. At minimum, add a warning to the query result that Gage and other clients can see.

## Workaround in use

The domain description carries query rules, and an Atlas skill (`/atlas/config/skills/mcdonalds-ops-queries`)
tells Gage to: filter only in `WHERE`, keep each joined path in one `MATCH`, join through relationships, pass
only scalars through `WITH`, add `EquipmentClassCode` filters, and sanity-check columns that should vary.
