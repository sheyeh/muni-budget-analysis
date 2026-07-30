# Example inputs/outputs, by pipeline level

Resolves GitHub issue #12 ("Order folder structure for input/output
examples across pipeline levels"). One directory per pipeline stage
(`CONTEXT.md`'s four stages: scraping, file processing, file analysis, web
UI), each holding real committed output samples that double as regression
fixtures -- not engine-named directories that don't generalize across
stages.

| Directory | Stage | Status |
|---|---|---|
| `level1-scraping/` | scraping | not built yet (placeholder) |
| `level2-processing/` | file processing | built (`src/muni_budget_analysis/processing`) |
| `level2.5-scope-filter/` | row/column scope filtering | POC only (`docs/adr/0003-*`) |
| `level3-analysis/` | file analysis (category/unit normalization) | spike only (`pipeline/analysis/`) |
| `level4-web/` | web UI | not built yet (placeholder) |

## Conventions

- **Raw sample inputs** stay in `budget_examples/` at the repo root (the
  shared level-1-output/level-2-input pool), not duplicated under
  `level1-scraping/`. It's referenced by all stages, not owned by one.
- **Committed output examples mirror the real runtime output shape
  exactly** (e.g. `level2-processing/{muni_id}/` matches
  `data/processed/{muni_id}/{filename_stem}/`'s file names), so they can be
  used as regression fixtures, not just documentation. `{muni_id}` values
  under 1000 here are synthetic placeholders (no level-1 scraper exists
  yet to assign real semel-yishuv codes) -- see each stage's README for the
  full id-to-source mapping.
- **Large files** (roughly >2MB) are gitignored with a `{filename}.link.txt`
  sidecar explaining what's missing and how to regenerate it, per the
  large-file convention in `CLAUDE.md` (originally documented on
  `worktree-level2-pipeline`). Never fabricate a hosting link -- say
  explicitly when one doesn't exist yet.
- **Throwaway spike output** (anything a `scripts/spike_*.py` script
  writes to `scripts/spike_output/`) is gitignored and never committed
  directly. If a spike produces something worth keeping as a real
  example or a sign-off deliverable, move it into the relevant
  `level*/` directory here instead (e.g. `level2.5-scope-filter/poc/`).

## Handshake docs

Contract docs between adjacent stages live at the repo root, not nested
under `docs/examples/` (they're specs, not samples):
`docs/handshake-level2-level3.md` (level 2 + 2.5 output -> level 3 input).

## Unrelated to this convention

`docs/examples/document_ai/` and `docs/examples/gcp_vision/` are OCR-engine
comparison spikes (Document AI vs. Vision API vs. docling), not pipeline
stage output -- correctly named after the engine they're evaluating, left
as-is.
