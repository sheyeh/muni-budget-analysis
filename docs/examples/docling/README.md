# Docling extraction examples

Reference outputs from `scripts/spike_docling.py` (Task 0 validation spike,
see `prd.md` and `docs/adr/0001-docling-primary-extraction-engine.md`).
Each subfolder holds the native/lossless export (`native.json`, via
`DoclingDocument.export_to_dict()`) and the markdown export (`document.md`,
via `DoclingDocument.export_to_markdown()`) for one sample municipal budget
PDF in `budget_examples/`.

**tel_aviv_2026.pdf required a GPU to convert.** A first attempt on CPU
(even_yehuda_2025, 1pp) took 78.7s in ACCURATE mode — extrapolated to
tel_aviv's 364pp that's multiple hours, not feasible on a laptop. Converted
instead on a GCP Compute Engine spot VM with an NVIDIA T4
(`n1-standard-4`, `pytorch-2-9-cu129-ubuntu-2204-nvidia-580` image); see
`docs/gcp-gpu-docling.md` for the process, gotchas, and the reusable
provisioning script (`scripts/gcp_gpu_spike.sh`).

## Key finding: OCR engine choice

Docling's default OCR engine (EasyOCR) has **no Hebrew support** — `he` is
absent from `easyocr.config.all_lang_list` on the installed version, and
forcing `lang=["he"]` raises `ValueError` at model init. Since these budget
PDFs are Hebrew, all forced-OCR conversions below use **Tesseract**
(`TesseractCliOcrOptions`, `lang=["heb", "eng"]`) instead, which does ship a
Hebrew (`heb`) trained-data model. This is relevant to the `PdfPipelineOptions`
choice in the PRD: EasyOCR is not a viable OCR backend for this project as
configured; Tesseract must be the OCR fallback for scanned Hebrew PDFs.

## elyakin_2026

- **Pages:** 3
- **Mode:** forced OCR (Tesseract, `heb+eng`) — no extractable text layer
  detected by the `pypdf`-based auto-check
- **Output sizes:** `native.json` ~126 KB, `document.md` ~5.4 KB
- **Tables:** 2 (income table, expense table)
- **Table fidelity:** Row structure and the 2-column layout (amount /
  label) survive intact and most numeric cells are correct, but OCR noise
  regularly corrupts adjacent Hebrew label text into garbage
  Latin/mixed-script tokens (e.g. `DANN`, `icecream`, `ANIONS`, `BAe`) and
  occasionally merges two source rows into one garbled cell — so the shape
  is trustworthy but label text needs a human/second pass, not just amounts.

## tel_aviv_2026

- **Pages:** 364
- **Mode:** default text-layer extraction (vectored PDF, `do_ocr=False`),
  ACCURATE TableFormer mode, run on GPU (NVIDIA T4, `--device cuda`)
- **Elapsed:** 1053.1s (~17.5 min) on GPU. Not run to completion on CPU
  (see above — hours, not attempted).
- **Output sizes:** `native.json` ~100 MB, `document.md` ~2.7 MB
- **Tables:** 353
- **Table fidelity:** code `631` (מימון והוצאות ריבית עמלה) lands as
  `19,640,900 / 20,000,000 / 20,000,000` in separate cells, exactly matching
  the PRD Task 0 acceptance check — no merged-cell corruption on this row.
  Zero conversion errors across all 364 pages.

## even_yehuda_2025

- **Pages:** 1 (a single dense page, not the 2pp originally guessed)
- **Mode:** default text-layer extraction (vectored PDF, `do_ocr=False`)
- **Output sizes:** `native.json` ~513 KB, `document.md` ~14 KB
- **Tables:** 1 (9-column budget detail table, ~40 rows)
- **Table fidelity:** High — every numeric and label cell renders as its
  own separate cell with no merging or OCR noise; this is the cleanest
  output of the three and confirms text-layer extraction is reliable when a
  real text layer is present.

## mate_yehuda_2024

- **Pages:** 3
- **Mode:** forced OCR (Tesseract, `heb+eng`) — scanned/image-only PDF, no
  text layer
- **Output sizes:** `native.json` ~135 KB, `document.md` ~5.4 KB
- **Tables:** 2 (income table, expense table)
- **Table fidelity:** Same pattern as elyakin_2026 — the 2-column
  structure and most amounts extract correctly, but several row labels are
  OCR-garbled (e.g. `הההההההההההההה--` for what should be a placeholder/em-dash
  cell) and at least one pair of rows collapses into a single merged,
  unreadable cell. Forced-OCR output is usable for amounts but not reliable
  for label text without cleanup.
