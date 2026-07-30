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
Per-table fields produced by the new scope-filtering stage (between stages 2 and 3, see `docs/adr/0003-*`), stored in `scoped.json`, never in `normalized.json` — the normalized document stays stage 2's untouched contract. `year_axis` says which dimension of a table carries the year (`column` — the common case, e.g. `even_yehuda_2025`'s comparison table; `row` — multi-year forecast tables like `jerusalem_2026`'s 15-year debt-repayment schedule; or `none` — no year dimension detectable, table unusable for fiscal-year-specific extraction). `keep` is a per-column-or-per-row boolean along that axis: `true` for the slice matching the target fiscal year, and for structural (non-year) columns/rows needed to interpret it (category names, codes); `false` for every other year's slice.
_Avoid_: whole-table in/out labels — a single real budget table routinely mixes target-year and other-year columns (or rows) together, so scoping is a row/column selection within a table, not a table-level classification.
