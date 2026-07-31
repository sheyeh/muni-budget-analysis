# Level 2: file processing -- example output

Real output of `src/muni_budget_analysis/processing/run.py` (the level-2
batch entrypoint) against every file in `budget_examples/`, one directory
per `muni_id`. Shape mirrors `data/processed/{muni_id}/{filename_stem}/`
exactly: `manifest.json`, `normalized.json`, `document.md`,
`docling_native.json` (docling-routed files only -- `excel_native` files
have no docling export). See `CONTEXT.md` for what `normalized.json`
means and `docs/handshake-level2-level3.md` for its full schema.

## `muni_id` mapping

All values below 1000 are **synthetic placeholders**, not real
semel-yishuv (Ministry of Interior) codes -- no level-1 scraper exists yet
to assign real ones. Kept consistent with `tests/test_run_e2e.py`'s
existing 901/902/903 convention.

| muni_id | source file | pipeline_used | pages | notes |
|---|---|---|---|---|
| 901 | `even_yehuda_2025.pdf` | `docling_pdf` | 1 | vectored, flat table |
| 902 | `mate_yehuda_2024.pdf` | `docling_pdf_ocr` | 3 | scanned |
| 903 | `elad_2022.xlsx` | `excel_native` | -- | only Excel sample |
| 904 | `tel_aviv_2026.pdf` | `docling_pdf` | 363 | vectored, hierarchical codes; ran on GCP spot NVIDIA L4 GPU (~17.6min), `normalized.json`/`docling_native.json` gitignored (~13.7MB/~100MB, see `.link.txt`) |
| 905 | `shafir_2026.pdf` | `docling_pdf_ocr` | 144 | scanned; ran on GCP spot NVIDIA L4 GPU (~15min), `normalized.json`/`docling_native.json` gitignored (~2.77MB/~21.85MB, see `.link.txt`) |
| 906 | `elyakin_2026.pdf` | `docling_pdf_ocr` | 3 | scanned |
| 907 | `gezer_2026.pdf` | `docling_pdf` | 52 | vectored; ran on GCP T4 GPU |
| 908 | `jaljulya_2026.pdf` | `docling_pdf_ocr` | 9 | scanned; ran on GCP T4 GPU |
| 909 | `jerusalem_2026.pdf` | `docling_pdf` | 17 | vectored; ran on GCP T4 GPU |
| 910 | `lachish_2026.pdf` | `docling_pdf_ocr` | 3 | scanned |

`tel_aviv_2026.xlsx` was not processed separately: `run.py` derives its
output directory from `Path(budget_filename).stem`, which collides with
`tel_aviv_2026.pdf`'s stem under the same `muni_id` -- a real gap in the
pipeline (both can't be processed into the same `muni_id` today without
one overwriting the other), left as a follow-up rather than fixed here
(surgical scope).

## Regenerating

```
python -m muni_budget_analysis.processing.run \
    --level1-manifest <path-to-a-level1-manifest.json> \
    --raw-dir data/raw --processed-dir data/processed
```

Large/scanned PDFs (`tel_aviv_2026.pdf`, `shafir_2026.pdf`, and anything
similarly sized) should run on a GCP T4 GPU rather than CPU -- see
`docs/gcp-gpu-docling.md`. For files needing forced OCR on a Linux host,
set `TESSERACT_CMD=tesseract` (the default in `pdf_pipeline.py` is a
Windows path) and make sure `tesseract-ocr`/`tesseract-ocr-heb` are
installed.
