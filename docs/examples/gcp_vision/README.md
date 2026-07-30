# GCP Vision OCR spike (docling/Tesseract comparison)

Follow-up to the Task 0 docling validation spike. `docs/examples/docling/README.md`
found that docling's forced-OCR path (Tesseract, `heb+eng`) gets table
row/column structure and numeric amounts right on scanned PDFs, but regularly
garbles Hebrew label text. `docs/adr/0001-docling-primary-extraction-engine.md`
named cloud Document AI/Vision as the documented fallback for exactly this
case. This spike (`scripts/spike_gcp_ocr.py`) runs Google Cloud Vision's
`DOCUMENT_TEXT_DETECTION` over the same two scanned samples to check that
fallback empirically.

## Result: Hebrew text accuracy — clear win for Vision

Every garbled cell called out in the docling README reads correctly in
Vision's output. Side by side, from `mate_yehuda_2024.pdf`:

| Row | Docling + Tesseract (`document.md`) | GCP Vision (`vision_text.txt`) |
|---|---|---|
| Water utility income | `הההההההההההההה--` | `מפעל המים` (correct) |
| Other government receipts | `תקבוליס ממשלתיים DANN` | `תקבולים ממשלתיים אחרים` (correct) |
| Other Interior Ministry grants | `מענקיס DANN ממשרד הפנים` | `מענקים אחרים ממשרד הפנים` (correct) |
| Discount/deficit-coverage rows | `הההההההההההחחהה= 537,374`, `14,943 הההההההההההההה--` | `537,374` / `14,943` on clean separate lines, correct adjacent labels |

Same pattern holds on `elyakin_2026.pdf` — no Latin-script corruption
(`DANN`, `icecream`, `BAe`, etc. from the docling README) appears anywhere in
Vision's output; all Hebrew renders as real Hebrew words.

Both files ran in single-digit seconds (3 pages each, ~4.5s / ~5.8s) at 300dpi
page renders — no GPU, no batch job, nothing beyond a per-page API call.

## Tradeoff: table structure is lost

Vision's plain `document_text_detection` returns reading-order text blocks,
not a table model. On these two-column (amount / label) budget tables, the
numeric column and the label column come back as **separate blocks** (see
`vision_text.txt` — page 2 of `mate_yehuda_2024` lists all the amounts, then
all the labels, in two runs) rather than paired per-row the way docling's
`DoclingDocument` tables are. Docling's forced-OCR output kept the row/column
pairing intact (just with corrupted text in some cells); Vision inverts that
tradeoff — correct text, lost pairing.

Implication: naively swapping Vision in as "the OCR product" for scanned
files would trade a text-accuracy problem for a table-reconstruction problem.
Two paths forward, in order of promise:

1. **Use Vision (or Tesseract) only to re-OCR text *within* the table cells
   docling already located**, keeping docling's layout/table-structure model
   (which doesn't depend on OCR text quality, only on visual layout) and
   only replacing the OCR backend feeding its cells. Docling's OCR options
   are pluggable (`ocr_options=` on `PdfPipelineOptions`); needs checking
   whether a custom/remote OCR backend can be wired in there, or whether
   cell bounding boxes from a docling `ocr=False`-but-image-input run could
   be cropped and sent to Vision individually as a post-process.
2. **Use Document AI's dedicated processor** (not plain Vision) — it returns
   structured tables/paragraphs with bounding boxes, not just raw text, so
   it may reconstruct the row/column pairing itself instead of needing (1).
   Not tried in this spike (requires provisioning a Document AI processor,
   more setup than a stateless Vision call) — natural next step given how
   decisive the text-accuracy result already is.

## Recommendation

Given cost is not a constraint (GCP credits) and a large share of the
~200-file corpus is scanned, the Tesseract Hebrew label-garbling problem is
real and Vision resolves it cleanly on text — but table-structure
reconstruction needs one more spike (option 2 above, or the hybrid in
option 1) before committing to a specific integration into `router.py`'s
`docling_pdf_ocr` path. Don't swap in plain Vision wholesale; validate
Document AI's structured table extraction next.

## Reproduce

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable vision.googleapis.com --project YOUR_PROJECT_ID
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
python scripts/spike_gcp_ocr.py
```
