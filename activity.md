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
