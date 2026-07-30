"""
pdf_pipeline.py

Docling-backed PDF conversion for municipal budget documents (Task 5, see
prd.md and docs/adr/0001-docling-primary-extraction-engine.md). Wraps
docling's DocumentConverter -- both variants, text-layer and forced-OCR --
behind a single isolated/swappable function (convert_pdf) per ADR-0001
Carve-out 2: no interface/abstraction layer, just a function boundary that
could be swapped out later if the engine choice changes.

convert_pdf() also does stage-2 structural work that belongs here rather
than in normalize.py (Task 6): merging multi-page table continuations
(repeated header row, no intervening section break) into one logical table,
per prd.md's Task 5 bullet and CONTEXT.md's "Structural extraction" stage.

The dict returned by convert_pdf() is the engine-agnostic intermediate
shape that normalize.py consumes -- it never imports docling or touches a
DoclingDocument.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    OcrOptions,
    PdfPipelineOptions,
    TableFormerMode,
    TesseractCliOcrOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc.document import DoclingDocument, SectionHeaderItem, TableItem, TitleItem

logger = logging.getLogger(__name__)

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


def build_ocr_options(backend: str = "tesseract") -> OcrOptions:
    """
    Factory for docling OCR options, keyed by backend name.

    This is the single seam for adding a second OCR engine later (e.g. a
    GCP-native OCR backend) without touching build_pipeline_options(),
    make_converter(), or convert_pdf() -- add a new branch here only.
    """
    if backend == "tesseract":
        return TesseractCliOcrOptions(
            lang=["heb", "eng"],
            force_full_page_ocr=True,
            tesseract_cmd=TESSERACT_CMD,
            path=TESSDATA_DIR,
        )
    raise ValueError(f"Unknown OCR backend: {backend!r}")


def build_pipeline_options(
    force_ocr: bool, table_mode: TableFormerMode, ocr_backend: str = "tesseract"
) -> PdfPipelineOptions:
    opts = PdfPipelineOptions()
    opts.do_table_structure = True
    opts.table_structure_options.do_cell_matching = True
    opts.table_structure_options.mode = table_mode

    if force_ocr:
        opts.do_ocr = True
        opts.ocr_options = build_ocr_options(ocr_backend)
    else:
        # Default settings: text-layer extraction. OCR left off explicitly
        # (rather than trusting docling's own auto-fallback heuristic) so
        # this is purely a test of the PDF's real text layer + TableFormer,
        # with OCR noise ruled out as a confound.
        opts.do_ocr = False
    return opts


def make_converter(
    force_ocr: bool, table_mode: TableFormerMode, ocr_backend: str = "tesseract"
) -> DocumentConverter:
    pipeline_options = build_pipeline_options(force_ocr, table_mode, ocr_backend)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )


def get_docling_version() -> str:
    """Return the installed docling package version string."""
    import docling

    return docling.__version__


def _extract_table_rows(table: TableItem) -> List[List[Dict[str, Any]]]:
    """
    Walk a table's fully-populated grid (table.data.grid: list[num_rows] of
    list[num_cols] of TableCell) and return one row of cell dicts per grid
    row, skipping grid positions covered by a spanning cell that originates
    elsewhere (start_row_offset_idx/start_col_offset_idx != the grid
    position -- the same TableCell object occupies every cell it spans).

    is_header = cell.column_header or cell.row_header. Note these flags are
    model-predicted and not always reliable for a visual header row
    (verified empirically: sometimes False for an actual header row) --
    treat as a best-effort signal.
    """
    rows_out: List[List[Dict[str, Any]]] = []
    for r_idx, row in enumerate(table.data.grid):
        row_out = []
        for c_idx, cell in enumerate(row):
            if cell.start_row_offset_idx != r_idx or cell.start_col_offset_idx != c_idx:
                continue  # covered by a span originating elsewhere
            row_out.append({
                "text": cell.text,
                "row_span": cell.row_span,
                "col_span": cell.col_span,
                "is_header": bool(cell.column_header or cell.row_header),
            })
        rows_out.append(row_out)
    return rows_out


def merge_multipage_tables(doc: DoclingDocument) -> List[List[TableItem]]:
    """
    Group consecutive TableItems (in reading order via doc.iterate_items())
    into multi-page-continuation groups, per prd.md's "repeated header row,
    no intervening section break" requirement -- BOTH conditions, not just
    adjacency:

      1. No heading item (SectionHeaderItem/TitleItem) appears between the
         two tables.
      2. The candidate table's first grid row (its header row, by
         convention) has the same cell texts as the group's first table's
         first grid row.

    Adjacency alone is not sufficient: mate_yehuda_2024.pdf has an income
    table and an expense table separated only by a picture (no heading) --
    condition 2 (different header rows) correctly keeps them as separate
    groups.
    """
    groups: List[List[TableItem]] = []
    group_header_texts: Optional[List[str]] = None
    heading_since_last_table = True  # doc start counts as a break

    for item, _level in doc.iterate_items():
        if isinstance(item, (SectionHeaderItem, TitleItem)):
            heading_since_last_table = True
            continue
        if not isinstance(item, TableItem):
            continue

        rows = _extract_table_rows(item)
        header_texts = [cell["text"] for cell in rows[0]] if rows else []

        if (
            not heading_since_last_table
            and groups
            and group_header_texts is not None
            and header_texts == group_header_texts
        ):
            groups[-1].append(item)
        else:
            groups.append([item])
            group_header_texts = header_texts

        heading_since_last_table = False

    return groups


def _assemble_group_rows(group: List[TableItem]) -> List[List[Dict[str, Any]]]:
    """
    Concatenate a merge group's tables into one row list, dropping the
    repeated header row from every table after the first. Group membership
    (merge_multipage_tables) already proved each subsequent table's row 0
    text-matches the group's header, so it's always dropped here -- do NOT
    re-derive "is this a header" from cell["is_header"], which is a
    model-predicted flag documented as unreliable (see _extract_table_rows)
    and would silently leave a duplicated header row in the merged output
    if TableFormer mis-flags it.
    """
    rows: List[List[Dict[str, Any]]] = []
    for group_idx, table in enumerate(group):
        table_rows = _extract_table_rows(table)
        if group_idx == 0:
            rows.extend(table_rows)
        else:
            rows.extend(table_rows[1:])
    return rows


def convert_pdf(
    path: Path,
    pipeline_used: str,
    table_mode: TableFormerMode = TableFormerMode.ACCURATE,
    ocr_backend: str = "tesseract",
) -> Dict[str, Any]:
    """
    Convert one PDF via docling and return the engine-agnostic intermediate
    shape (sections + merged tables + page_count) that normalize.py (Task 6)
    consumes without ever importing docling or touching a DoclingDocument.

    pipeline_used: "docling_pdf" (text-layer) or "docling_pdf_ocr" (forced
    OCR) -- as produced by router.route().

    Caveat for normalize.py (Task 6): rows are NOT guaranteed rectangular.
    _extract_table_rows() skips grid positions covered by a spanning cell
    that originates elsewhere, so a row containing a col-span/row-span cell
    can come out shorter than `num_cols` (= the longest row seen). None of
    the small in-repo samples exercise this (checked: zero spanned cells in
    elyakin_2026/even_yehuda_2025/mate_yehuda_2024's native.json exports),
    but tel_aviv_2026.pdf -- the ADR-0001 "hard problem" file with
    hierarchical, multi-column tables -- is exactly the kind of document
    likely to have them. A consumer doing positional column indexing on
    `rows` should not assume every row has `num_cols` entries.
    """
    force_ocr = pipeline_used == "docling_pdf_ocr"
    converter = make_converter(force_ocr, table_mode, ocr_backend)

    logger.info("Converting %s (pipeline_used=%s)", path, pipeline_used)
    result = converter.convert(str(path))
    doc = result.document

    # Pass 1: walk reading order once to build sections and record, for
    # each pre-merge table (in traversal order), the section_id of the
    # nearest preceding heading (None if no heading precedes it yet).
    sections: List[Dict[str, Any]] = []
    table_items: List[TableItem] = []
    table_section_ids: List[Optional[str]] = []
    current_section_id: Optional[str] = None

    for item, _level in doc.iterate_items():
        if isinstance(item, (SectionHeaderItem, TitleItem)):
            page_no = item.prov[0].page_no if item.prov else None
            section_id = f"sec-{len(sections)}"
            sections.append({
                "section_id": section_id,
                "title": item.text,
                "page_range": [page_no, page_no] if page_no is not None else None,
                "table_ids": [],
            })
            current_section_id = section_id
        elif isinstance(item, TableItem):
            table_items.append(item)
            table_section_ids.append(current_section_id)

    sections_by_id = {sec["section_id"]: sec for sec in sections}
    # Keyed by TableItem.self_ref (e.g. "#/tables/0") rather than id(table):
    # merge_multipage_tables() below does its own separate iterate_items()
    # pass, and while docling's ref-resolution happens to return the same
    # object each time on the installed version (verified empirically),
    # self_ref is the documented stable identifier docling itself uses for
    # this purpose -- not reliant on an object-identity implementation detail.
    section_id_by_table_ref = {
        table.self_ref: section_id for table, section_id in zip(table_items, table_section_ids)
    }

    # Pass 2 (merge_multipage_tables does its own iterate_items() pass):
    # group tables into multi-page-continuation groups.
    groups = merge_multipage_tables(doc)

    tables_out: List[Dict[str, Any]] = []
    for i, group in enumerate(groups):
        table_id = f"table-{i}"
        # A merge group's section_id is the section of its FIRST table --
        # all tables in a group share the same nearest-heading by
        # construction, since nothing separates them (per merge_multipage_tables).
        section_id = section_id_by_table_ref.get(group[0].self_ref)

        pages: List[int] = []
        for table in group:
            for prov in table.prov:
                pages.append(prov.page_no)
        rows = _assemble_group_rows(group)

        num_cols = max((len(row) for row in rows), default=0)
        tables_out.append({
            "table_id": table_id,
            "section_id": section_id,
            "page_range": [min(pages), max(pages)] if pages else None,
            "num_rows": len(rows),
            "num_cols": num_cols,
            "rows": rows,
        })

        if section_id is not None and section_id in sections_by_id:
            sections_by_id[section_id]["table_ids"].append(table_id)

    return {
        "sections": sections,
        "tables": tables_out,
        "page_count": len(doc.pages),
    }


def dump_native_json(doc: DoclingDocument, out_path: Path) -> None:
    """Write doc's full native/lossless export as JSON to out_path."""
    try:
        data = doc.export_to_dict()
    except AttributeError:
        data = doc.model_dump(mode="json")
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def dump_markdown(doc: DoclingDocument, out_path: Path) -> None:
    """Write doc's markdown export to out_path."""
    out_path.write_text(doc.export_to_markdown(), encoding="utf-8")
