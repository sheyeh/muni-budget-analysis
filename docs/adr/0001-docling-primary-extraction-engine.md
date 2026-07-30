# Docling as primary document-processing engine for level 2

Level 2 ingests ~200 heterogeneous municipal budget files (scanned PDF, vectored PDF, Excel) with no SLA. We chose docling over cloud Document AI (Azure/Google Document Intelligence) and table-only tools (Camelot/pdfplumber/tabula-py) because it unifies vectored + scanned PDF handling (automatic OCR fallback) in one local, free Python library, and its TableFormer model targets the corpus's hard problem directly: preserving hierarchical, multi-column table structure (see `tel_aviv_2026.pdf`, `even_yehuda_2025.pdf`).

## Considered options

- **Cloud Document AI** (Azure/Google) — stronger track record on scanned/low-quality documents and explicit Hebrew OCR support, but adds external dependency and per-page cost for no benefit on the vectored-PDF majority case. Kept as a documented fallback (not built) if docling's Hebrew OCR proves insufficient once `mate_yehuda_2024.pdf` (scanned) is validated.
- **unstructured.io** — similar all-in-one scope to docling, no stronger RTL/Hebrew evidence, no compelling advantage.
- **Camelot / pdfplumber / tabula-py** — table-only, no OCR, likely to fail on the hierarchical merged-cell tables in the sample corpus; no unified story for scanned PDFs or Excel.

## Status

Locked in for vectored PDFs and the overall unified pipeline shape. The Hebrew/RTL validation item above has now been checked and **did** turn something up: `docs/examples/docling/README.md` found docling's forced-OCR path (Tesseract `heb+eng`) gets table structure and numeric amounts right on scanned samples, but regularly garbles Hebrew label text. `docs/examples/gcp_vision/README.md` (GCP Vision `DOCUMENT_TEXT_DETECTION` spike, `scripts/spike_gcp_ocr.py`) confirms the fallback resolves this — every garbled cell in the docling output reads correctly via Vision — but plain Vision loses table row/column structure in exchange, so scanned-PDF handling isn't settled yet: next step is validating Document AI's structured table extraction (or a hybrid using docling's layout model with Vision-sourced cell text) before changing `router.py`'s `docling_pdf_ocr` path. Given the corpus's scanned-file share and that cost is not a constraint (GCP credits), this is worth resolving before Task 7's full batch run.
