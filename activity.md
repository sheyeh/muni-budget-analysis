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
Tier B (GPU VM run on tel_aviv_2026.pdf/shafir_2026.pdf) remains open,
pending explicit go-ahead for GCP GPU VM cost.

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
tel_aviv_2026.pdf/shafir_2026.pdf, code-631 check) remains an outstanding
follow-up requiring an explicit go-ahead for GCP VM cost.

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
