# Docling as primary document-processing engine for level 2

Level 2 ingests ~200 heterogeneous municipal budget files (scanned PDF, vectored PDF, Excel) with no SLA. We chose docling over cloud Document AI (Azure/Google Document Intelligence) and table-only tools (Camelot/pdfplumber/tabula-py) because it unifies vectored + scanned PDF handling (automatic OCR fallback) in one local, free Python library, and its TableFormer model targets the corpus's hard problem directly: preserving hierarchical, multi-column table structure (see `tel_aviv_2026.pdf`, `even_yehuda_2025.pdf`).

## Considered options

- **Cloud Document AI** (Azure/Google) — stronger track record on scanned/low-quality documents and explicit Hebrew OCR support, but adds external dependency and per-page cost for no benefit on the vectored-PDF majority case. Kept as a documented fallback (not built) if docling's Hebrew OCR proves insufficient once `mate_yehuda_2024.pdf` (scanned) is validated.
- **unstructured.io** — similar all-in-one scope to docling, no stronger RTL/Hebrew evidence, no compelling advantage.
- **Camelot / pdfplumber / tabula-py** — table-only, no OCR, likely to fail on the hierarchical merged-cell tables in the sample corpus; no unified story for scanned PDFs or Excel.

## Status

Locked in. Hebrew/RTL reading-order behavior remains an open validation item (not a reason to reconsider the engine choice) — tracked as a spike, not a blocker to this decision.
