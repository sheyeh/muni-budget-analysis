# Document AI (Form Parser) spike — third leg of the OCR comparison

Follow-up to `docs/examples/gcp_vision/README.md`, which found Cloud Vision
fixes docling+Tesseract's Hebrew label-garbling but loses table row/column
pairing. This spike (`scripts/spike_document_ai.py`) sends the same two
scanned samples to a Document AI **Form Parser** processor
(`FORM_PARSER_PROCESSOR`, region `us`), which returns actual structured
tables (`document.pages[].tables[].header_rows`/`body_rows`), to check
whether it gets both correct text *and* correct pairing.

It doesn't, on either count, consistently. Two separate problems showed up:

## 1. Table row-grouping is unreliable

Form Parser's own table-cell detection frequently merges 2-4 logical rows
into one cell instead of one label + one amount per row (see `tables.md` for
both files — e.g. `mate_yehuda_2024` page 2's fourth row runs
`תקבולים אחרים / הכנסות חד פעמיות ... / סה"כ הכנסות לפני הנחות ... / 537,374`
all in a single cell). This is the opposite failure mode from what was
hoped for: docling's TableFormer (visual-geometry-based) reliably gets
one-row-per-line on these same tables; Form Parser's table model does not.

## 2. OCR text quality is scan-quality-dependent, and worse than Vision on the noisier file

- **`mate_yehuda_2024.pdf`** (cleaner scan): table cell text is fully
  correct — every label and amount matches the docling/Vision baseline,
  including the previously-garbled cells (`מפעל המים`, `תקבולים ממשלתיים
  אחרים`, `מענקים אחרים ממשרד הפנים`). Noise only appears in non-table
  decorative regions (letterhead logos, signature stamps — the same
  regions docling rendered as bare `<!-- image -->` placeholders).
- **`elyakin_2026.pdf`** (noisier/lower-quality scan): table cells contain
  substantial hallucinated noise not present in *either* prior OCR attempt
  — tokens like `aniiglading`, `130111111`, `STARS`, `HOSTE`, `Utopia`,
  `LAMARO` mixed directly into cell text. This is **worse** than
  docling+Tesseract's garbling on the same file, and clearly worse than
  Vision, which read this file cleanly (see `docs/examples/gcp_vision/
  elyakin_2026/vision_text.txt`).

Ruled out as confounds before concluding this is a real quality gap:
- **Language hints**: re-ran with `ocr_config.hints.language_hints=["he"]`
  explicitly set (the script's current state) — no improvement on
  `elyakin_2026`, same noise pattern.
- **Rasterization/resolution**: Document AI processes the PDF's embedded
  raster directly, while the Vision spike explicitly rendered pages to PNG
  at 300dpi first — a plausible reason Vision might have gotten a better
  source image. Tested directly: sent the identical 300dpi-rendered PNG
  (used for Vision) to Document AI instead of the raw PDF. Same class of
  garbage output. Not a rasterization artifact — Document AI's OCR model
  is simply less robust on this specific scan than Vision's.

Both files' **totals** (`552,317` for `mate_yehuda_2024`, `41,626` for
`elyakin_2026`) come through correctly in all three approaches (docling,
Vision, Document AI) despite the label/noise differences — the failure mode
here is label-text and row-structure fidelity, not gross numeric errors.

## Conclusion / recommendation

Across all three approaches now tried on these two scanned samples:

| | Table structure (row/col pairing) | Hebrew text accuracy |
|---|---|---|
| docling + Tesseract | Correct | Garbled labels (both files) |
| Cloud Vision (`DOCUMENT_TEXT_DETECTION`) | Not returned (plain text) | Correct (both files) |
| Document AI (Form Parser) | Unreliable (both files) | Correct on clean scan, worse-than-Tesseract on noisy scan |

No single product wins on both axes. Document AI's generic Form Parser is
not the drop-in answer the ADR's fallback option implied — it's strictly
worse than Vision on OCR robustness here, and its table model isn't
reliable enough to justify using it for structure either.

**Recommendation for `router.py`'s `docling_pdf_ocr` path**: keep docling's
TableFormer for table geometry/structure (it's the one component in this
whole comparison that reliably got row/column pairing right on both scanned
files), and replace only the OCR text-recognition step feeding it —
Tesseract → Cloud Vision — rather than adopting Document AI at all. This
means either (a) checking whether docling's pluggable `ocr_options` can call
out to a custom/remote OCR backend, or (b) a post-process that crops each
table cell's region (docling already knows the bounding boxes from its
layout model) and re-OCRs just that crop via Vision. Not built in this
spike — this is the concrete next implementation step, to be coordinated
with whoever owns `router.py` on `worktree-level2-pipeline`, not built here.

## Reproduce

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable documentai.googleapis.com --project YOUR_PROJECT_ID
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
# Create a Form Parser processor once (console, or):
curl -s -X POST \
  "https://us-documentai.googleapis.com/v1/projects/YOUR_PROJECT_ID/locations/us/processors" \
  -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
  -H "Content-Type: application/json" \
  -d '{"type":"FORM_PARSER_PROCESSOR","displayName":"muni-budget-form-parser-spike"}'
python scripts/spike_document_ai.py --processor projects/<num>/locations/us/processors/<id>
```
