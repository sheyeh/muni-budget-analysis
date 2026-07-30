# PRD: Level 2 — File Processing Pipeline

Implements the design in the approved plan (`docs/adr/0001-*`, `docs/adr/0002-*`, `CONTEXT.md`, and the level-2 design plan). Tasks run in order — later tasks depend on earlier ones' outputs (schemas, helpers).

Full design context for every task: `CONTEXT.md` (glossary: structural extraction, normalized document, budget line item, muni_id), `docs/adr/0001-docling-primary-extraction-engine.md`, `docs/adr/0002-excel-native-extraction-path.md`. Sample files: `budget_examples/tel_aviv_2026.pdf` (364pp, vectored, hierarchical codes), `budget_examples/even_yehuda_2025.pdf` (2pp, vectored, flat table), `budget_examples/mate_yehuda_2024.pdf` (4pp, scanned/image-only, no Excel sample yet).

## Task 0: Validation spike

**Goal:** confirm docling's table-structure extraction is trustworthy before building the full pipeline on top of it.
- Run docling (default, no OCR) on `tel_aviv_2026.pdf` and `even_yehuda_2025.pdf`. Inspect `DoclingDocument` JSON: are numeric table columns correctly separated per row/column? Does a table like the one at code `631` (amounts `19,640,900 / 20,000,000 / 20,000,000`) come out with each amount in its own cell?
- Run docling with OCR forced on `mate_yehuda_2024.pdf` (scanned). Inspect OCR confidence and whether Hebrew text is usable.
- Deliverable: a throwaway script (`scripts/spike_docling.py` or similar, ok to delete after) plus a short written finding: does docling's output justify proceeding as designed, or does something need to change?
- **This gates everything else** — if docling's table fidelity is poor on these real samples, stop and flag before Tasks 1-7 build on a bad foundation.

## Task 1: Scaffolding & dependencies

- `pyproject.toml` (or `requirements.txt`, match whichever convention fits an all-Python repo with no existing config) with `docling`, `openpyxl`, `pandas`, a magic-byte sniffing lib (`python-magic` or `filetype`).
- Package skeleton: `pipeline/processing/__init__.py` (empty/minimal).
- No logic yet — just an installable, importable package.

## Task 2: `manifest.py`

- `manifest.json` read/write helpers, per the schema in the plan (`muni_id`, `source_filename`, `source_sha256`, `detected_type`, `pipeline_used`, `docling_version`, `processed_at`, `status`, `page_count`, `warnings`, `outputs`).
- `status` rule (from `CONTEXT.md`/plan): `failed` = no usable output at all; `partial` = output produced but `warnings` non-empty; `success` = output produced, no warnings.

## Task 3: `ingest.py`

- Resolve a level-1 input record (`{muni_id, budget_filename, source: {kind, value}}`) to a local file path. `kind == "url"` downloads once into `raw/{muni_id}/{filename}` and treats it as `local_path` from then on.
- Compute sha256. Skip reprocessing if `processed/{muni_id}/{filename_stem}/manifest.json` already exists with matching hash (cache-by-hash, per plan).
- Detect real file type via magic bytes — never trust the extension in `budget_filename`.

## Task 4: `router.py`

- Given the sniffed type + a quick check for PDF text-layer presence, decide: `pdf_vectored` → `docling_pdf`, `pdf_scanned` → `docling_pdf_ocr`, `xlsx`/`xls` → `excel_native`.
- Pure decision logic, no conversion work here.

## Task 5: `pdf_pipeline.py`

- Docling conversion, both variants (text-layer / forced-OCR), isolated behind one function per ADR-0001/Carve-out 2 (no abstraction/interface — just an isolated function, swappable later if needed).
- Merge multi-page table continuations (repeated header row, no intervening section break) into one logical table — this is stage 2's job per `CONTEXT.md`'s "Structural extraction" entry, not stage 3's.

## Task 6: `excel_pipeline.py` + `normalize.py`

- `excel_pipeline.py`: openpyxl/pandas native read, gap-based table-region segmentation per sheet (per ADR-0002). No Excel sample exists yet — build this generically and flag it as unvalidated; don't over-invest in heuristics until a real sample exists.
- `normalize.py`: adapter functions mapping (a) docling's native document → `normalized.json` schema (sections + tables, flat rows, no code-hierarchy or fiscal-year interpretation — that's stage 3's job) and (b) excel native tables → the same schema. One adapter per pipeline type, same output contract.

## Task 7: `run.py` + end-to-end verification

- Batch entrypoint: iterate a level-1 manifest (list of `{muni_id, budget_filename, source}`), run ingest → route → convert → normalize → persist for each, writing `processed/{muni_id}/{filename_stem}/{manifest.json, normalized.json, docling_native.json, document.md}`.
- Sequential, single-process — no worker pool (per plan; no SLA, avoid speculative complexity).
- A failed/partial file must not crash the batch.
- End-to-end verification: run against all 3 real samples via a synthetic level-1 manifest. Confirm each `normalized.json` has non-empty `tables`; for Tel Aviv confirm code `631` maps to `19,640,900 / 20,000,000 / 20,000,000`.
