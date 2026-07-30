"""
scripts/spike_gcp_ocr.py

Follow-up to the Task 0 docling validation spike (scripts/spike_docling.py,
docs/adr/0001-docling-primary-extraction-engine.md). That ADR named cloud
Document AI/Vision as a documented fallback "if docling's Hebrew OCR proves
insufficient" -- docs/examples/docling/README.md then found exactly that on
the scanned samples: docling's forced-OCR path (Tesseract heb+eng) gets table
row/column structure and numeric amounts right, but regularly garbles Hebrew
label text (e.g. the "מפעל המים" row rendering as "הההההההההההההה--" in
mate_yehuda_2024's document.md).

This script runs Google Cloud Vision's DOCUMENT_TEXT_DETECTION over the same
scanned PDFs' pages and dumps the recognized text per page, so the two can be
compared line-by-line on the same known-bad cells. It renders each page to a
PNG via pypdfium2 (already a docling dependency, no new render lib needed) and
sends the image bytes directly to Vision -- no GCS bucket required for
single-page-at-a-time calls.

Auth: uses Application Default Credentials. Run once, outside this repo,
before using this script:

    gcloud auth application-default login
    gcloud config set project YOUR_PROJECT_ID
    gcloud services enable vision.googleapis.com --project YOUR_PROJECT_ID
    gcloud auth application-default set-quota-project YOUR_PROJECT_ID

No credentials are read, printed, or stored by this script or checked into
the repo -- google-cloud-vision's client picks up ADC from the environment
on its own.

Usage:
    python scripts/spike_gcp_ocr.py                              # both scanned samples
    python scripts/spike_gcp_ocr.py --only mate_yehuda_2024.pdf
    python scripts/spike_gcp_ocr.py --dpi 300
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

import pypdfium2 as pdfium
from google.cloud import vision

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = REPO_ROOT / "budget_examples"
OUTPUT_ROOT = REPO_ROOT / "docs" / "examples" / "gcp_vision"

# Both are scanned/image-only PDFs per docs/examples/docling/README.md --
# the only two files where docling's OCR path (and its Hebrew label garbling)
# is actually in play. even_yehuda_2025/tel_aviv_2026 are vectored and already
# extract cleanly without OCR, so there's nothing to compare there.
TARGETS = ["mate_yehuda_2024.pdf", "elyakin_2026.pdf"]


def render_page_png(pdf: pdfium.PdfDocument, page_index: int, dpi: int) -> bytes:
    page = pdf[page_index]
    scale = dpi / 72
    bitmap = page.render(scale=scale)
    pil_image = bitmap.to_pil()
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return buf.getvalue()


def ocr_page(client: vision.ImageAnnotatorClient, png_bytes: bytes) -> vision.TextAnnotation:
    image = vision.Image(content=png_bytes)
    # DOCUMENT_TEXT_DETECTION (vs plain TEXT_DETECTION) is tuned for dense
    # document pages rather than sparse scene text -- the right mode for
    # budget-table scans.
    response = client.document_text_detection(image=image, image_context={"language_hints": ["he"]})
    if response.error.message:
        raise RuntimeError(response.error.message)
    return response.full_text_annotation


def run_one(client: vision.ImageAnnotatorClient, filename: str, dpi: int, summary_lines: list[str]) -> None:
    src = SAMPLES_DIR / filename
    out_dir = OUTPUT_ROOT / src.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== {filename} ===")
    if not src.exists():
        msg = f"MISSING FILE: {src}"
        print(msg)
        summary_lines.append(f"{filename}: {msg}")
        return

    pdf = pdfium.PdfDocument(str(src))
    n_pages = len(pdf)

    t0 = time.time()
    page_texts = []
    try:
        for i in range(n_pages):
            png_bytes = render_page_png(pdf, i, dpi)
            annotation = ocr_page(client, png_bytes)
            page_texts.append(annotation.text if annotation else "")
    except Exception as exc:  # noqa: BLE001 - spike: one bad file must not kill the run
        elapsed = time.time() - t0
        summary_lines.append(f"{filename}: EXCEPTION after {elapsed:.1f}s: {exc!r}")
        raise
    elapsed = time.time() - t0

    full_text = "\n\n--- page break ---\n\n".join(page_texts)
    out_path = out_dir / "vision_text.txt"
    out_path.write_text(full_text, encoding="utf-8")

    print(f"pages={n_pages} elapsed={elapsed:.1f}s chars={len(full_text):,} output={out_path}")
    summary_lines.append(f"{filename}: pages={n_pages} elapsed={elapsed:.1f}s chars={len(full_text):,}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--only",
        help="Comma-separated substrings to filter target filenames (e.g. --only mate_yehuda)",
    )
    p.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Render resolution for page images sent to Vision (default 300)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    targets = TARGETS
    if args.only:
        filters = [f.strip() for f in args.only.split(",")]
        targets = [t for t in TARGETS if any(f in t for f in filters)]
        if not targets:
            print(f"--only matched nothing in {TARGETS}")
            sys.exit(1)

    client = vision.ImageAnnotatorClient()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    summary_lines: list[str] = []
    for filename in targets:
        run_one(client, filename, args.dpi, summary_lines)

    print("\n=== SUMMARY ===")
    print("\n".join(summary_lines))
    print(f"\nFull output written under: {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
