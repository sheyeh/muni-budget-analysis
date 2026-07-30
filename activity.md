# Activity Log

Completion log for `prd.md` tasks. One entry per task, written when reviewer approves + tests pass.

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

## Task 3: ingest.py

`compute_sha256`/`detect_file_type`/`resolve_source`/`is_already_processed`/
`ingest`. 12/12 tests pass. Reviewer found a real bug (url download
buffered the whole response into memory instead of streaming — would OOM
on large files like shafir_2026.pdf) — fixed.
