# Activity Log

Completion log for `prd.md` tasks. One entry per task, written when reviewer approves + tests pass.

## PR #5 follow-up: Excel ground-truth fidelity check

Closed the excel_pipeline.py fidelity gap flagged in PR #5's test plan
(previously smoke-tested only). Added `TestRealSamplesFidelity` to
`tests/test_excel_pipeline.py`, asserting `extract_excel_tables()` output
against cell values read directly from `elad_2022.xlsx` and
`tel_aviv_2026.xlsx` (independently verified via openpyxl): region bounds,
header/data cell text, and span values. Along the way, confirmed neither
real sample exercises the multi-region gap-splitting branch (both are one
continuous region, zero blank-row gaps, zero merged cells) — that path is
still only covered by the synthetic test. Also surfaced (not fixed, per
ADR-0002's "don't over-invest in heuristics" guidance) that
`segment_sheet_tables`'s "first row of region = header" rule mislabels
tel_aviv_2026.xlsx's row 1 (a single-cell title banner) as the header
instead of row 2's real column names — asserted explicitly in the new test
so a future fix has something to flip. 6/6 excel_pipeline tests pass.
Tier B (GPU VM run on tel_aviv_2026.pdf/shafir_2026.pdf) is now done —
see "Tier B: GPU verification of the production run.py path" below.

## Task 1: Scaffolding & dependencies

`src/muni_budget_analysis/processing/` subpackage created; `docling`,
`pypdf`, `filetype` added to `requirements.txt`. Reviewer approved (one
scope-leak finding about an unrelated spike-script change in the same
diff, resolved by splitting into a separate commit). Import verified:
`python -c "import muni_budget_analysis.processing"`.

## Task 2: manifest.py

`compute_status`/`build_manifest_record`/`write_manifest`/`read_manifest`.
6/6 tests pass. Reviewer found one issue (warnings/outputs stored by
reference instead of copied) — fixed, retested, clean.

## Task 4: router.py

`has_text_layer` + `route()`. 7/7 tests pass against real PDF/xlsx
samples. Reviewer approved with no issues.

## Task 6 (1/2): excel_pipeline.py

`read_workbook`/`segment_sheet_tables`/`extract_excel_tables`. 4/4 tests
pass. Reviewer found a real bug (`read_only=True` breaks merged_cells
access) — fixed — plus 2 documentation-only findings, addressed via
docstring notes rather than added complexity (per ADR-0002's
don't-over-invest guidance).

## Task 7: run.py + Tier A e2e verification

`load_level1_manifest`/`process_one`/`run_batch`/`main`. `pdf_pipeline.py`
gained `convert_pdf_with_document()` for a single-conversion dump of
`docling_native.json`/`document.md` alongside `normalized.json`.
Reviewer found a real TOCTOU bug (skip-cache path could return `None`
and crash `run_batch`) and an unguarded exception-handler write, both
fixed; also correctly flagged the e2e test's Tier A/B scope split as
undocumented in the test file itself (it traces back to the approved
plan, `.claude/plans/piped-noodling-ocean.md` — now cross-referenced in
the test docstring). Full suite: 40/40 tests pass. **This completes all
7 prd.md tasks** — the Level-2 file processing pipeline is implemented
end-to-end for the Tier A (CPU, fast) sample set. Tier B (GPU,
tel_aviv_2026.pdf/shafir_2026.pdf, code-631 check) is now done too — see
"Tier B: GPU verification of the production run.py path" below.

## Task 6 (2/2): normalize.py

`pdf_result_to_normalized`/`excel_to_normalized`/`write_normalized`. Both
pipelines' results wrap into the identical envelope. Reviewer found
output-aliases-input list issues (same category as Task 2/6a findings) —
fixed with shallow copies, test updated to assert non-aliasing. 4/4 tests
pass. Task 6 complete (both excel_pipeline.py and normalize.py landed).

## Task 5: pdf_pipeline.py

`convert_pdf`/`merge_multipage_tables`/`build_ocr_options` (OCR-backend
seam for future GCP-native OCR). Docling 2.116.0 API verified empirically
first (`iterate_items()`, `table.data.grid`, `TableItem.self_ref`) before
implementation. Reviewer found a real HIGH-severity bug (unreliable
`is_header` flag left a duplicated header row in merged tables uncorrected)
and a robustness issue (`id()` vs `self_ref` for cross-pass table
identity) — both fixed, plus the missing positive-merge test added
(synthetic `DoclingDocument`, not mocks). 5/5 tests pass.

## Task 3: ingest.py

`compute_sha256`/`detect_file_type`/`resolve_source`/`is_already_processed`/
`ingest`. 12/12 tests pass. Reviewer found a real bug (url download
buffered the whole response into memory instead of streaming — would OOM
on large files like shafir_2026.pdf) — fixed.

## Tier B: GPU verification of the production run.py path (2026-07-30)

Ran `tel_aviv_2026.pdf` and `shafir_2026.pdf` through the real
`run_batch()`/`run.py` entrypoint (not the spike script) on a GCP T4 VM,
per the outstanding follow-up in `tests/test_run_e2e.py` and GitHub #6.
Project: `qwiklabs-gcp-03-e1024cd263b6`, zone `us-central1-b`.

- **Spot provisioning was not viable here**: the VM was preempted twice
  within ~15 minutes (once mid-conversion), so the run VM was switched to
  on-demand (`--provisioning-model` omitted) instead. Worth noting for
  any future large batch run (Task 7) on a similarly quota-constrained
  project.
- `tel_aviv_2026.pdf` (363pp per docling's page count): converted in
  **1081.7s (~18min)**, `status=success`. Code `631` in the resulting
  `normalized.json` maps to `19,640,900 / 20,000,000 / 20,000,000` —
  reproducing the Task 0 spike's finding through the production
  normalize.py output (table-32 and table-93, both matching).
- `shafir_2026.pdf` (144pp, scanned): first attempt failed —
  `pdf_pipeline.py`'s `TESSERACT_CMD` default is a hardcoded Windows path
  (`C:\Program Files\Tesseract-OCR\tesseract.exe`), so
  `pipeline_used=docling_pdf_ocr` crashes at model-init on any Linux host
  unless `TESSERACT_CMD=tesseract` (or the real binary path) is set via
  env var. **Not fixed here** (out of scope for a verification run) —
  flagging as a real portability bug for a follow-up, since Task 7's
  real batch run would hit this on any Linux/GCP host. Rerun with the
  env var set: converted in **1551.1s (~25.9min)**, `status=success`.
- Batch summary: 2/2 success, 0 failed.

## Full-corpus level-2 + level-2.5 run + folder reorg (issue #12) (2026-07-31)

Merged `worktree-level2-pipeline` and `worktree-level2.5-scope-filter`
(already both on `origin/main` via PR #5/#10) into one integration branch
and ran the real pipelines end-to-end against all 10 files in
`budget_examples/` (previously only `tel_aviv_2026`/`shafir_2026` had been
run through production `run.py`).

- **Level 2** (`run.py`): 5 small/CPU files run locally
  (`even_yehuda_2025`, `mate_yehuda_2024`, `elad_2022`, `elyakin_2026`,
  `lachish_2026`); 3 more (`gezer_2026` 52pp, `jaljulya_2026` 9pp scanned,
  `jerusalem_2026` 17pp) run on a fresh GCP T4 VM (`level2-batch-gpu`,
  same project as the earlier Tier B run) since CPU ACCURATE-mode
  extrapolates to tens of minutes for the larger ones; VM deleted after.
  10/10 success, 0 failed. `muni_id` assignments: 901-903, 906-910 (new),
  904-905 (existing, from Tier B).
- **Level 2.5** (new `scripts/run_scope_classify.py`, still POC-shaped
  per ADR-0003): ran the real classifier (Vertex AI `gemini-2.5-flash`,
  same qwiklabs project) against real `normalized.json` tables for all 10
  documents — the first time this classifier has run against production
  `normalize.py` output rather than hand-transcribed samples. Capped at 3
  tables/doc as a cost/quota guard (`tel_aviv_2026` alone has 353 tables).
  10/10 documents got a `scoped.json`.
- **Folder reorg** (GitHub issue #12): introduced
  `docs/examples/{level1-scraping,level2-processing,level2.5-scope-filter,level3-analysis,level4-web}/`,
  one directory per `CONTEXT.md` pipeline stage. Migrated
  `docs/examples/docling/` (engine-named, pre-`normalized.json`) into
  `level2-processing/{muni_id}/`, matching the real `data/processed/`
  runtime shape exactly. Moved the level-2.5 POC's real deliverable
  (`scripts/spike_output/scope_classify/`) into
  `level2.5-scope-filter/poc/` and gitignored `scripts/spike_output/`
  going forward (was untracked cruft in every `git status`, per the
  issue). Moved the level-3 spike's committed output (`out/`,
  `summarize_data.csv`, previously loose at repo root) into
  `level3-analysis/`. See `docs/examples/README.md` for the full
  convention.
- **New**: `docs/handshake-level2-level3.md` — the schema contract
  between level 2+2.5 output and level 3 input, written against the real
  files above (not spec-only). Flags that `pipeline/analysis/` (the
  existing level-3 spike) still reads docling's `native.json` directly
  instead of `normalized.json`/`scoped.json` — a real gap, not fixed here
  (out of surgical scope for this task).
- Also surfaced, not fixed: `run.py` derives its per-file output directory
  from `Path(budget_filename).stem`, so `tel_aviv_2026.pdf` and
  `tel_aviv_2026.xlsx` would collide under the same `muni_id` — only the
  PDF was processed here.
