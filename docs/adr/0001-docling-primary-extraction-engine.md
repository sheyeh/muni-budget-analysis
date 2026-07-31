# Docling as primary document-processing engine for level 2

Level 2 ingests ~200 heterogeneous municipal budget files (scanned PDF, vectored PDF, Excel) with no SLA. We chose docling over cloud Document AI (Azure/Google Document Intelligence) and table-only tools (Camelot/pdfplumber/tabula-py) because it unifies vectored + scanned PDF handling (automatic OCR fallback) in one local, free Python library, and its TableFormer model targets the corpus's hard problem directly: preserving hierarchical, multi-column table structure (see `tel_aviv_2026.pdf`, `even_yehuda_2025.pdf`).

## Considered options

- **Cloud Document AI / Vision** (Google) — originally kept as a documented fallback (not built) if docling's Hebrew OCR proved insufficient. It did (see Status): Document AI's Form Parser was spiked and ruled out (unreliable table structure, inconsistent OCR quality — see `docs/examples/document_ai/README.md`); Cloud Vision's raw OCR was spiked and adopted in a hybrid role (see Status) — not as a full engine swap, but as docling's OCR backend for scanned pages.
- **unstructured.io** — similar all-in-one scope to docling, no stronger RTL/Hebrew evidence, no compelling advantage.
- **Camelot / pdfplumber / tabula-py** — table-only, no OCR, likely to fail on the hierarchical merged-cell tables in the sample corpus; no unified story for scanned PDFs or Excel.

## Status

Locked in for vectored PDFs and the overall unified pipeline shape. The Hebrew/RTL validation item above has now been checked end-to-end across three approaches on the two scanned samples:

- `docs/examples/docling/README.md`: docling's forced-OCR path (Tesseract `heb+eng`) gets table structure right, garbles Hebrew label text.
- `docs/examples/gcp_vision/README.md`: Cloud Vision (`DOCUMENT_TEXT_DETECTION`) gets Hebrew text right on both files, but returns plain reading-order text — no table structure.
- `docs/examples/document_ai/README.md`: Document AI's Form Parser processor was tried as the structured-table candidate. It doesn't deliver reliable row/column pairing on either file (rows frequently merge), and its OCR text quality is scan-dependent — correct on the cleaner sample, worse than Tesseract on the noisier one (confirmed not a rasterization artifact via a direct 300dpi-image control test). **Ruled out** as the fallback.

**Decision**: no single product wins on both structure and text accuracy, so the fix is a hybrid, not a product swap — keep docling's TableFormer for table geometry (the one component that reliably paired rows/columns on both scanned files), and replace only the OCR text-recognition step feeding it (Tesseract → Cloud Vision). Cost is not a constraint (GCP credits) and a large share of the ~200-file corpus is scanned, so this was done before Task 7's full batch run.

**Implemented** (issue #4): via docling's pluggable `ocr_options` — `PdfPipelineOptions.ocr_options` turned out to have a real OCR-engine plugin surface (`docling.models.factories.get_ocr_factory`, a `BaseOcrModel`/`OcrOptions` pair registered against it), not just a config-value seam, so the per-cell-crop post-process alternative wasn't needed. See `src/muni_budget_analysis/processing/cloud_vision_ocr.py` (the `CloudVisionOcrModel`/`CloudVisionOcrOptions` pair and registration) and `pdf_pipeline.py`'s `build_ocr_options("cloud_vision")`. `run.py`'s scanned-PDF (`docling_pdf_ocr`) path now requests this backend by default.
