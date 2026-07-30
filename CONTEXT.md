# Muni Budget Analysis

Pipeline turning scraped municipal budget files into a structured, browsable dataset. Stages: scraping, file processing, scope filtering, file analysis, web UI.

## Language

**Structural extraction**:
The stage-2 (file processing) output for one source file: sections and tables captured faithfully from the document's visual/positional layout (docling for PDF, openpyxl/pandas for Excel), with zero domain interpretation. Table rows are flat; a hierarchical code like `6111` is just a cell string, not a parsed parent/child relationship. Multi-page table continuations (repeated header row, no intervening section break) ARE merged into one logical table in stage 2 — that's a structural/visual fact, not domain interpretation.
_Avoid_: "parsed budget data", "extracted budget" — these imply semantic understanding stage 2 does not do.

**Muni ID** (`muni_id`):
The official Israeli municipality identifier (semel yishuv, Ministry of Interior / CBS code), reused as-is rather than inventing a project-internal ID — lets other public datasets be joined on the same key later.
_Avoid_: "municipality code" as a project-invented term — it's an existing external identifier, not something this project defines.

**Normalized document**:
The `normalized.json` file per source file — the concrete artifact holding one file's structural extraction (sections + tables). This is stage 2's contract with stage 3.
_Avoid_: "processed file" (ambiguous — could mean the manifest, the docling native export, or this).

**Budget line item**:
A semantically resolved row produced by stage 3: a classification code placed in its hierarchy, a resolved fiscal year/amount-type per value (actual vs. budgeted vs. execution %), read off of one or more table rows in a normalized document. This is the "well-defined table of interesting values" stage 3 exists to produce.
_Avoid_: "table row" for this — a table row is stage 2's raw, uninterpreted unit; a budget line item is stage 3's interpreted one.

**Year axis** / **keep**:
Per-table fields produced by the new scope-filtering stage (between stages 2 and 3, see `docs/adr/0003-*`), stored in `scoped.json`, never in `normalized.json` — the normalized document stays stage 2's untouched contract. `year_axis` says which dimension of a table carries the year (`column` — the common case, e.g. `even_yehuda_2025`'s comparison table; `row` — multi-year forecast tables like `jerusalem_2026`'s 15-year debt-repayment schedule; or `none` — no year dimension detectable, table unusable for fiscal-year-specific extraction). `keep` is a per-column-or-per-row boolean along that axis: `true` for the slice matching the target fiscal year, and for structural (non-year) columns/rows needed to interpret it (category names, codes, and — per `docs/adr/0004-*` — execution-rate % and change/delta columns, which describe the target year's own execution rather than carrying a different year); `false` for every other year's slice.
_Avoid_: whole-table in/out labels — a single real budget table routinely mixes target-year and other-year columns (or rows) together, so scoping is a row/column selection within a table, not a table-level classification.

**Classification code**:
A code from the national standard chart-of-accounts for Israeli local authorities (תקן תקציבי אחיד), e.g. `631` — shared and hierarchical (parent/child codes), not muni-specific. A budget line item's code is a foreign key into this shared taxonomy, not a copy of whatever string appeared in the source cell, so line items compare across munis. Populated top-down from the official code list (a tracked, separate sourcing task), not inferred bottom-up from whatever codes happen to appear in processed documents.
_Avoid_: "budget code" as a project-invented term — it names an existing external standard, not something this project defines.

**Amount type**:
The closed vocabulary distinguishing what kind of value a budget line item's amount represents: `budgeted`, `actual_current_prices`, `actual_adjusted_prices`, `execution_pct`, `change`. Closed deliberately — a source column stage 3 can't map to one of these is a warning, not a silently-added new type. `execution_pct` and `change` are "structural, keep regardless of year" for scope-filtering purposes (`docs/adr/0004-*`): they describe the target year's own execution/change, not a different year's data, even though their source column header rarely names a specific year.
_Avoid_: conflating with `year_axis`/`keep` — those decide which table slice survives into stage 3; amount type is what stage 3 calls the value once it has it.

**Budget coverage**:
Whether a muni's budget for a given fiscal year was found and processed at all — tracked per `(muni_id, fiscal_year)`. A row's absence means "not yet attempted"; an explicit `not_found` status means scraping actively looked and confirmed no document exists for that muni-year. The full expected muni × year matrix, including gaps, is a query (muni list × year range, compared against what actually exists), not a stored/pre-seeded field.
_Avoid_: treating a missing row as a confirmed gap — only an explicit `not_found` status means that; absence just means the work hasn't happened yet.
