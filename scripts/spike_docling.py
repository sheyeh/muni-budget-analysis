"""
scripts/spike_docling.py

Task 0 validation spike support script (see prd.md "## Task 0: Validation
spike" and docs/adr/0001-docling-primary-extraction-engine.md).

Runs docling's DocumentConverter over the sample municipal budget PDFs in
budget_examples/ and exports, per file, into
docs/examples/docling/<file_stem>/:

    native.json   - full DoclingDocument native/lossless export
                     (DoclingDocument.export_to_dict())
    document.md   - markdown export (DoclingDocument.export_to_markdown())

These outputs are checked into the repo as long-lived reference examples
(NOT deleted after the spike), so this script is kept around and is safe to
re-run to regenerate them (e.g. after a docling upgrade).

Modes per file:
  - tel_aviv_2026.pdf     -> default text-layer extraction (vectored PDF)
  - even_yehuda_2025.pdf  -> default text-layer extraction (vectored PDF)
  - mate_yehuda_2024.pdf  -> forced OCR (scanned/image-only PDF, no text layer)
  - elyakin_2026.pdf      -> auto-detected: checked via pypdf for a text
                             layer at runtime; forced OCR only if no page has
                             extractable text, default extraction otherwise.
                             The resolved mode is printed and included in the
                             per-file log line.

Usage:
    python scripts/spike_docling.py                    # all 4 files
    python scripts/spike_docling.py --fast              # TableFormer FAST mode (quicker smoke test)
    python scripts/spike_docling.py --only even_yehuda_2025.pdf,elyakin_2026.pdf

Known API-drift risk: docling's public API (module paths for
PdfPipelineOptions/InputFormat, OCR-option classes) has changed across
releases. Before trusting this script, verify against the installed version:

    python -c "import docling; print(docling.__version__)"
    python -c "from docling.datamodel.pipeline_options import PdfPipelineOptions, EasyOcrOptions, TableFormerMode; from docling.datamodel.base_models import InputFormat; from docling.document_converter import DocumentConverter, PdfFormatOption; print('imports ok')"

If an import here fails, fix the import path/field name to match the
installed version -- the logic below should not need to change.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    AcceleratorDevice,
    AcceleratorOptions,
    PdfPipelineOptions,
    TableFormerMode,
    TesseractCliOcrOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = REPO_ROOT / "budget_examples"
OUTPUT_ROOT = REPO_ROOT / "docs" / "examples" / "docling"

# NOTE: docling's default OCR engine (EasyOCR) does not support Hebrew at all
# (checked: 'he' is absent from easyocr.config.all_lang_list on the installed
# version) -- forcing lang=["he"] raises ValueError at model init. These
# budget PDFs are Hebrew, so forced-OCR mode uses Tesseract instead, which
# does have a Hebrew ("heb") trained-data model. Tesseract must be installed
# separately (e.g. `winget install UB-Mannheim.TesseractOCR`) with heb.traineddata
# available in a tessdata directory; point TESSERACT_CMD / TESSDATA_DIR below
# (or the env vars of the same name) at your install if they differ.
TESSERACT_CMD = os.environ.get(
    "TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
TESSDATA_DIR = os.environ.get("TESSDATA_DIR")  # None -> Tesseract's own default


@dataclass
class SpikeTarget:
    filename: str
    mode: str  # "default" | "ocr" | "auto"
    note: str


TARGETS = [
    SpikeTarget(
        "tel_aviv_2026.pdf",
        "default",
        "364pp hierarchical codes, multi-year amount columns, vectored",
    ),
    SpikeTarget(
        "even_yehuda_2025.pdf",
        "default",
        "2pp flat summary table, vectored",
    ),
    SpikeTarget(
        "mate_yehuda_2024.pdf",
        "ocr",
        "4pp scanned/image-only, no text layer, OCR forced",
    ),
    SpikeTarget(
        "elyakin_2026.pdf",
        "auto",
        "new sample, type unknown -- text layer checked at runtime via pypdf",
    ),
]


def has_text_layer(pdf_path: Path) -> bool:
    """Return True if any page of the PDF has extractable text."""
    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if len(text) > 0:
            return True
    return False


def build_pipeline_options(
    force_ocr: bool, table_mode: TableFormerMode, device: AcceleratorDevice
) -> PdfPipelineOptions:
    opts = PdfPipelineOptions()
    opts.do_table_structure = True
    opts.table_structure_options.do_cell_matching = True
    opts.table_structure_options.mode = table_mode
    opts.accelerator_options = AcceleratorOptions(device=device)

    if force_ocr:
        opts.do_ocr = True
        opts.ocr_options = TesseractCliOcrOptions(
            lang=["heb", "eng"],
            force_full_page_ocr=True,
            tesseract_cmd=TESSERACT_CMD,
            path=TESSDATA_DIR,
        )
    else:
        # Default settings: text-layer extraction. OCR left off explicitly
        # (rather than trusting docling's own auto-fallback heuristic) so
        # this is purely a test of the PDF's real text layer + TableFormer,
        # with OCR noise ruled out as a confound.
        opts.do_ocr = False
    return opts


def make_converter(
    force_ocr: bool, table_mode: TableFormerMode, device: AcceleratorDevice
) -> DocumentConverter:
    pipeline_options = build_pipeline_options(force_ocr, table_mode, device)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )


def dump_native_json(doc, out_path: Path) -> None:
    try:
        data = doc.export_to_dict()
    except AttributeError:
        data = doc.model_dump(mode="json")
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def dump_markdown(doc, out_path: Path) -> None:
    out_path.write_text(doc.export_to_markdown(), encoding="utf-8")


def run_one(
    target: SpikeTarget,
    table_mode: TableFormerMode,
    device: AcceleratorDevice,
    summary_lines: list[str],
) -> None:
    src = SAMPLES_DIR / target.filename
    out_dir = OUTPUT_ROOT / src.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== {target.filename} ({target.mode}) - {target.note} ===")
    if not src.exists():
        msg = f"MISSING FILE: {src}"
        print(msg)
        summary_lines.append(f"{target.filename}: {msg}")
        return

    resolved_mode = target.mode
    if target.mode == "auto":
        has_text = has_text_layer(src)
        resolved_mode = "default" if has_text else "ocr"
        print(f"{target.filename}: text layer present={has_text} -> resolved_mode={resolved_mode}")

    force_ocr = resolved_mode == "ocr"
    converter = make_converter(force_ocr, table_mode, device)

    t0 = time.time()
    try:
        result = converter.convert(str(src))
    except Exception as exc:  # noqa: BLE001 - spike: one bad file must not kill the run
        elapsed = time.time() - t0
        traceback.print_exc()
        summary_lines.append(f"{target.filename}: EXCEPTION after {elapsed:.1f}s: {exc!r}")
        return
    elapsed = time.time() - t0

    doc = result.document
    status = getattr(result, "status", "unknown")

    native_path = out_dir / "native.json"
    md_path = out_dir / "document.md"
    dump_native_json(doc, native_path)
    dump_markdown(doc, md_path)

    n_tables = len(doc.tables)
    errors = getattr(result, "errors", [])
    print(
        f"status={status} elapsed={elapsed:.1f}s mode={resolved_mode} tables={n_tables} "
        f"errors={len(errors)} native.json={native_path.stat().st_size:,}B "
        f"document.md={md_path.stat().st_size:,}B"
    )
    for e in errors:
        print(f"  error: {e}")

    summary_lines.append(
        f"{target.filename}: status={status} mode={resolved_mode} elapsed={elapsed:.1f}s "
        f"tables={n_tables} errors={len(errors)}"
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--fast",
        action="store_true",
        help="Use TableFormerMode.FAST instead of ACCURATE (quicker smoke test, "
        "esp. useful before committing to the 364pp tel_aviv run)",
    )
    p.add_argument(
        "--only",
        help="Comma-separated substrings to filter target filenames (e.g. --only even_yehuda)",
    )
    p.add_argument(
        "--device",
        choices=["auto", "cpu", "cuda"],
        default="auto",
        help="Accelerator device for docling's layout/TableFormer models "
        "(default: auto-detect, picks CUDA if a GPU is visible to torch).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    table_mode = TableFormerMode.FAST if args.fast else TableFormerMode.ACCURATE

    targets = TARGETS
    if args.only:
        filters = [f.strip() for f in args.only.split(",")]
        targets = [t for t in TARGETS if any(f in t.filename for f in filters)]
        if not targets:
            print(f"--only matched nothing in {[t.filename for t in TARGETS]}")
            sys.exit(1)

    import docling

    device = {
        "auto": AcceleratorDevice.AUTO,
        "cpu": AcceleratorDevice.CPU,
        "cuda": AcceleratorDevice.CUDA,
    }[args.device]

    try:
        import torch

        cuda_available = torch.cuda.is_available()
        cuda_name = torch.cuda.get_device_name(0) if cuda_available else None
    except ImportError:
        cuda_available = "unknown (torch not importable)"
        cuda_name = None

    print(f"docling version: {getattr(docling, '__version__', 'unknown')}")
    print(f"table_mode: {table_mode}")
    print(f"requested device: {args.device} -> torch.cuda.is_available()={cuda_available} name={cuda_name}")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    summary_lines: list[str] = []
    for target in targets:
        run_one(target, table_mode, device, summary_lines)

    print("\n=== SUMMARY ===")
    print("\n".join(summary_lines))
    print(f"\nFull output written under: {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
