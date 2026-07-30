# Postgres/Supabase as the persistence layer, with a long/tidy fact table

Stage 3 (semantic resolution) needs a place to land resolved `budget_line_item`s for the stage-4 web UI to query, and nothing past stage 2's file-based `normalized.json` exists yet. We chose **Postgres via Supabase** over SQLite (the obvious choice at this scale — ~200-250 munis, ≤5 years, low-millions of fact rows, no concurrent writes) because we want auth and custom-web-app headroom beyond a browse/filter tool (a SQLite+Datasette pairing would have covered browse/filter alone perfectly well, and was seriously considered).

The fact table (`budget_line_item`) is modeled **long/tidy**: one row per `(classification_code, fiscal_year_value, amount_type, amount)`, not one row per source table row. This falls directly out of `CONTEXT.md`'s existing "budget line item" definition (a resolved fiscal-year/amount-type per value) and is forced by the source data itself — a single row in a muni's budget table spans several fiscal years and amount-types as separate columns (see `even_yehuda_2025` sample: 2023 actual, 2024 budgeted, 2024 actual current/adjusted, execution %, 2025 budgeted, all in one row).

`amount_type` is a **closed enum** (`budgeted | actual_current_prices | actual_adjusted_prices | execution_pct | change`), not an open/extensible reference table like `classification_code`. Unlike classification codes — hundreds of values, hierarchical, externally standardized by the national תקן תקציבי אחיד — amount-types are a small, well-understood financial vocabulary. A source column stage-3 can't map to one of these should raise a warning, not silently mint a new enum value; extending the enum is a deliberate schema migration.

## Integration with ADR-0003 (level 2.5 scope filtering)

Stage 3's actual input is `scoped.json` (ADR-0003's output), not `normalized.json` directly — `normalized.json` stays stage 2's untouched contract; `scoped.json` adds per-column/row `detected_year` + `keep` on top of it. Only `keep = true` slices reach stage 3, which means for most tables the surviving data is just the target fiscal year's slice — other years' columns/rows are dropped as noise before stage 3 ever sees them.

This resolves the open judgment call ADR-0003 left for "the level 3 team": **`execution_pct` and `change` columns count as "structural, keep regardless of year"**, same bucket as the bare label/code column — not because they lack a year, but because they're derived/comparative metrics *about* the target year's execution (percent of target-year budget executed, change from a prior count), not raw other-year data. ADR-0003's scope-classification step should widen its "structural" bucket accordingly, beyond just non-numeric label/code columns.

Consequence for the schema: after scope-filtering, `budget_line_item.fiscal_year_value` will equal `budget.fiscal_year` in the overwhelming common case — including for `execution_pct`/`change` rows, which describe the target year itself, not some other year. The field stays a separate column from `budget.fiscal_year` anyway (not collapsed into it) as a defensive measure: if a scope-filtering misclassification or a future row-axis forecast table lets a genuine other-year value through with `keep = true`, stage 3 should still record the year it actually read off the column header, not silently assume it matches the document's nominal year.

## Considered options

- **SQLite (+ Datasette)** — zero hosting cost, no server code, fits the read-only/browse use case perfectly at this scale. Rejected because auth and a more custom web app are wanted for stage 4, not just browse/filter.
- **Open reference table for `amount_type`** (mirroring `classification_code`'s pattern) — rejected because the vocabulary is small and domain-fundamental; letting it grow automatically risks OCR/header noise masquerading as new financial concepts.

## Status

Accepted. Full schema (muni / classification_code / budget / budget_line_item) and the stage-3 → Postgres write path (via an intermediate `line_items.json` artifact + a not-yet-built loader) are recorded in the data-modeling plan session; `classification_code`'s actual seed data (the official code list) is a tracked, separate open task.
