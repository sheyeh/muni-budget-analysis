"""
scripts/spike_document_ai.py

Second follow-up to the Task 0 docling validation spike, after
scripts/spike_gcp_ocr.py (see docs/examples/gcp_vision/README.md). That spike
found Cloud Vision's DOCUMENT_TEXT_DETECTION fixes docling+Tesseract's Hebrew
label-text garbling on scanned budget PDFs, but loses table row/column
pairing (Vision returns reading-order text blocks, not a table model).

This script sends the same two scanned PDFs to a Document AI **Form Parser**
processor instead, which returns actual structured tables
(document.pages[].tables[].header_rows / body_rows, each a list of cells with
a layout.text_anchor into the full document text) -- checking whether it gets
both correct Hebrew text AND correct row/column pairing, resolving the
tradeoff the Vision spike found.

Auth: uses Application Default Credentials, same as spike_gcp_ocr.py:

    gcloud auth application-default login
    gcloud config set project YOUR_PROJECT_ID
    gcloud services enable documentai.googleapis.com --project YOUR_PROJECT_ID
    gcloud auth application-default set-quota-project YOUR_PROJECT_ID

No credentials are read, printed, or stored by this script or checked into
the repo.

Requires a Form Parser processor to already exist (Document AI processors
are provisioned resources, not created implicitly per-call). Pass its full
resource name via --processor or the DOCUMENT_AI_PROCESSOR env var, e.g.:

    projects/<project-number>/locations/us/processors/<processor-id>

Usage:
    python scripts/spike_document_ai.py --processor projects/.../processors/...
    python scripts/spike_document_ai.py --only mate_yehuda_2024.pdf
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from google.cloud import documentai

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = REPO_ROOT / "budget_examples"
OUTPUT_ROOT = REPO_ROOT / "docs" / "examples" / "document_ai"

# Same two scanned/image-only PDFs as spike_gcp_ocr.py -- the only files
# where an OCR backend choice is actually in play (vectored PDFs extract
# cleanly via docling's text layer, no OCR needed).
TARGETS = ["mate_yehuda_2024.pdf", "elyakin_2026.pdf"]


def layout_text(layout: documentai.Document.Page.Layout, full_text: str) -> str:
    """Resolve a Layout's text_anchor segments into the actual substring.

    Document AI doesn't inline cell text -- each Layout carries text_anchor
    ranges (start/end byte offsets) into the single top-level document.text
    string. This is the standard resolution pattern from Google's own
    Document AI samples.
    """
    if not layout.text_anchor.text_segments:
        return ""
    parts = []
    for segment in layout.text_anchor.text_segments:
        start = int(segment.start_index) if segment.start_index else 0
        end = int(segment.end_index)
        parts.append(full_text[start:end])
    return "".join(parts).strip()


def row_to_cells(row: documentai.Document.Page.Table.TableRow, full_text: str) -> list[str]:
    return [layout_text(cell.layout, full_text) for cell in row.cells]


def dump_markdown(doc: documentai.Document, out_path: Path) -> None:
    lines = []
    for page_idx, page in enumerate(doc.pages):
        if not page.tables:
            continue
        lines.append(f"## Page {page_idx + 1}\n")
        for table_idx, table in enumerate(page.tables):
            lines.append(f"### Table {table_idx + 1}\n")
            header_rows = [row_to_cells(r, doc.text) for r in table.header_rows]
            body_rows = [row_to_cells(r, doc.text) for r in table.body_rows]
            for row in header_rows:
                lines.append("| " + " | ".join(row) + " |")
            if header_rows:
                lines.append("| " + " | ".join(["---"] * len(header_rows[0])) + " |")
            for row in body_rows:
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def dump_json(doc: documentai.Document, out_path: Path) -> None:
    structure = {"pages": []}
    for page in doc.pages:
        page_tables = []
        for table in page.tables:
            page_tables.append(
                {
                    "header_rows": [row_to_cells(r, doc.text) for r in table.header_rows],
                    "body_rows": [row_to_cells(r, doc.text) for r in table.body_rows],
                }
            )
        structure["pages"].append({"tables": page_tables})
    out_path.write_text(json.dumps(structure, ensure_ascii=False, indent=2), encoding="utf-8")


def run_one(
    client: documentai.DocumentProcessorServiceClient,
    processor_name: str,
    filename: str,
    summary_lines: list[str],
) -> None:
    src = SAMPLES_DIR / filename
    out_dir = OUTPUT_ROOT / src.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== {filename} ===")
    if not src.exists():
        msg = f"MISSING FILE: {src}"
        print(msg)
        summary_lines.append(f"{filename}: {msg}")
        return

    raw_document = documentai.RawDocument(
        content=src.read_bytes(), mime_type="application/pdf"
    )
    # Without an explicit language hint, Document AI's OCR auto-detects
    # script/language per token -- on these Hebrew scans that produced far
    # more hallucinated English-looking noise tokens than Vision's OCR got
    # with an explicit hint (see docs/examples/document_ai/README.md for the
    # before/after). Hebrew ("he") is the only hint passed since these are
    # single-language documents.
    process_options = documentai.ProcessOptions(
        ocr_config=documentai.OcrConfig(
            hints=documentai.OcrConfig.Hints(language_hints=["he"])
        )
    )
    request = documentai.ProcessRequest(
        name=processor_name,
        raw_document=raw_document,
        process_options=process_options,
    )

    t0 = time.time()
    result = client.process_document(request=request)
    elapsed = time.time() - t0
    doc = result.document

    n_tables = sum(len(page.tables) for page in doc.pages)
    text_path = out_dir / "document_ai_text.txt"
    tables_md_path = out_dir / "tables.md"
    tables_json_path = out_dir / "tables.json"

    text_path.write_text(doc.text, encoding="utf-8")
    dump_markdown(doc, tables_md_path)
    dump_json(doc, tables_json_path)

    print(
        f"pages={len(doc.pages)} elapsed={elapsed:.1f}s tables={n_tables} "
        f"chars={len(doc.text):,} output={out_dir}"
    )
    summary_lines.append(
        f"{filename}: pages={len(doc.pages)} elapsed={elapsed:.1f}s tables={n_tables} chars={len(doc.text):,}"
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--processor",
        default=os.environ.get("DOCUMENT_AI_PROCESSOR"),
        help="Full Document AI processor resource name "
        "(projects/<num>/locations/<loc>/processors/<id>). Defaults to "
        "DOCUMENT_AI_PROCESSOR env var.",
    )
    p.add_argument(
        "--only",
        help="Comma-separated substrings to filter target filenames (e.g. --only mate_yehuda)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.processor:
        print("ERROR: --processor or DOCUMENT_AI_PROCESSOR env var is required")
        sys.exit(1)

    targets = TARGETS
    if args.only:
        filters = [f.strip() for f in args.only.split(",")]
        targets = [t for t in TARGETS if any(f in t for f in filters)]
        if not targets:
            print(f"--only matched nothing in {TARGETS}")
            sys.exit(1)

    # Processor resource names embed their region (e.g. "locations/us"); the
    # client must be pointed at that region's API endpoint explicitly, it
    # does not infer this from the resource name.
    location = args.processor.split("/locations/")[1].split("/")[0]
    client_options = {"api_endpoint": f"{location}-documentai.googleapis.com"}
    client = documentai.DocumentProcessorServiceClient(client_options=client_options)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    summary_lines: list[str] = []
    for filename in targets:
        run_one(client, args.processor, filename, summary_lines)

    print("\n=== SUMMARY ===")
    print("\n".join(summary_lines))
    print(f"\nFull output written under: {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
