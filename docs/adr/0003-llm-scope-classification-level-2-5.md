# LLM-based row/column scope selection as a new stage between level 2 and level 3

Real samples show the "many other years" problem isn't whole tables being off-topic — it's that every real budget table is inherently multi-year by design. `even_yehuda_2025.pdf`'s single budget table has columns for 2023 actual / 2024 budget / 2024 actual / 2025 proposed, all in one table (exactly what `CONTEXT.md`'s "budget line item" is meant to read fiscal year off of). `jerusalem_2026.pdf` (364pp) has a 15-year debt-repayment forecast table ("תחזית פירעון מלוות העירייה לשנים 2040-2026"), same table shape, years as rows instead of columns. Whole-table classification (in-scope / out-of-scope) doesn't fit: the same table mixes target-year data with other-year data along one axis. What stage 3 needs is the *slice* of each table — the row or column — that belongs to the target fiscal year, plus whatever structural row/column (category name, code) is needed to interpret it. Everything else along that axis is the noise the user flagged.

`normalized.json` sections carry only heading titles (`item.text` at each heading, per `pdf_pipeline.py`) — no prose body is captured. So there is no narrative content for this stage to filter; the entire job is table-internal.

## Decision

New stage, level 2.5, between file processing (2) and file analysis (3). Input: one `normalized.json`. Output: a new artifact, `scoped.json`, non-destructive — `normalized.json` is untouched (stage 2's contract with stage 3 doesn't change).

Per table, in two steps:
1. **Detect year axis** — do this table's *columns* carry the year dimension (the common case), its *rows* (multi-year forecast tables), or neither (no year dimension detectable — e.g. a static lookup table, not usable for fiscal-year-specific extraction at all).
2. **Select the target-year slice** along that axis — each column (or row) gets a `detected_year` (nullable) and a `keep` boolean. `keep = true` when `detected_year` matches the target fiscal year (known from the level-1 input record, e.g. `jerusalem_2026` → 2026), or when the column/row is structural (a category-name/code column, not year-bearing) and therefore needed regardless of which year is kept. Everything else is `keep = false`.

Classifier input per table: column headers plus the first cell of every row (covers the row-axis case) — small payload, no full numeric grid sent, no hallucination surface from row data that doesn't change the axis/year judgment.

Backend: Vertex AI Gemini (flash tier — classification, not generation; team already has GCP experience in this repo: `docs/gcp-gpu-docling.md`, `docs/examples/document_ai`, `docs/examples/gcp_vision` from other worktrees' spikes). Isolated behind one function (`classify_table(section_title, headers, first_column_values, target_year) -> TableScope`), same isolation pattern as ADR-0001's docling carve-out — swappable, and a future heuristic pre-filter (cheap regex check on headers first, fall back to this function only when inconclusive) can wrap it later without changing the module boundary, output schema, or stage 3's contract.

Before full implementation: a POC (throwaway script, hand-picked table snippets from the real samples, real Vertex AI calls, real `scoped.json`-shaped output) is sent to the level 3 dev team for contract sign-off, before the classifier module/batch runner/tests are built. Same gating pattern as `prd.md` Task 0's docling validation spike.

## Considered options

- **Whole-table classification** (label each table `relevant`/`irrelevant` as a unit) — rejected. Doesn't fit the data: the real budget table itself mixes target-year and other-year columns in one table, so a table-level label can't express "keep this table but only some of its columns."
- **Heuristic-only (regex/keyword rules on headers)** — no GCP cost, deterministic, but brittle: Hebrew header phrasing already varies across the 7 sample municipalities, and the corpus is ~200 files across many municipalities. Rejected as the primary mechanism; worth adding later as a cheap pre-filter once real classification patterns are known (hybrid, below).
- **Hybrid (heuristics first pass, LLM fallback for low-confidence tables)** — cheapest at scale, but needs a heuristic baseline that doesn't exist yet, best mined from the LLM classifier's own output once run across the real corpus. Deferred, not rejected: the LLM-only design is built so this is additive later.
- **Filter-and-drop instead of tag-and-retain** — rejected. A misclassification would permanently lose data unless re-run from stage 2; tagging costs one extra field and keeps every option open (stage 3, a human reviewer, or a future heuristic pass can all still see what was excluded and why).

## Status

Proposed — POC not yet run. Next step: build the throwaway classification script against real samples (`even_yehuda_2025` expect column-axis, only 2025 kept; `jerusalem_2026` debt-forecast table expect row-axis, only 2026 kept), send output to the level 3 dev team for contract feedback before writing the classifier module, batch runner, or tests.
