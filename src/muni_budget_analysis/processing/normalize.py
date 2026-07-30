"""
normalize.py

Wraps each stage-2 pipeline's engine-specific result dict (pdf_pipeline's
convert_pdf() output or excel_pipeline's extract_excel_tables() output) into
the shared normalized.json envelope: {"muni_id", "source_filename",
"pipeline_used", "sections", "tables"}. Table row cell shapes ({"text",
"row_span", "col_span", "is_header"}) are already identical between the two
pipelines -- this module only reshapes sections/tables/table_ids, it never
touches cell contents.

This module does NOT import docling or openpyxl and does not reference a
DoclingDocument -- it only touches the plain-dict shapes the two pipeline
modules already produced.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

NORMALIZED_FILENAME = "normalized.json"


def pdf_result_to_normalized(
    pdf_result: Dict[str, Any],
    muni_id: int,
    source_filename: str,
    pipeline_used: str,
) -> Dict[str, Any]:
    """
    Wrap convert_pdf()'s return dict ({"sections", "tables", "page_count"})
    into the shared normalized.json envelope. pdf_result["sections"] is
    passed through unchanged. Each table in pdf_result["tables"] is passed
    through with "sheet_name": None added, since PDF tables have no sheet
    concept.
    """
    # Shallow-copy the outer sections/tables lists (and each table dict, via
    # {**table, ...}) so this function's output doesn't alias pdf_result's
    # own list/dict objects -- a caller mutating pdf_result afterward can't
    # silently change already-returned output. Row/cell data itself is NOT
    # deep-copied: it's produced fresh per convert_pdf() call and never
    # reused after normalization, and deep-copying it would be wasteful for
    # documents with hundreds of tables (e.g. tel_aviv_2026.pdf).
    tables = [
        {**table, "sheet_name": None}
        for table in pdf_result["tables"]
    ]
    return {
        "muni_id": muni_id,
        "source_filename": source_filename,
        "pipeline_used": pipeline_used,
        "sections": list(pdf_result["sections"]),
        "tables": tables,
    }


def excel_to_normalized(
    excel_result: Dict[str, Any],
    muni_id: int,
    source_filename: str,
) -> Dict[str, Any]:
    """
    Wrap extract_excel_tables()'s return dict ({"sheets": [{"sheet_name",
    "regions"}]}) into the shared normalized.json envelope. One section per
    sheet, one table per region within that sheet. Table IDs increment
    globally across all sheets (not reset per sheet), so they stay unique
    across the whole normalized.json. pipeline_used is always "excel_native"
    -- there's only one Excel pipeline.
    """
    sections = []
    tables = []
    table_counter = 0

    for i, sheet in enumerate(excel_result["sheets"]):
        section_id = f"sec-{i}"
        table_ids = []

        for region in sheet["regions"]:
            table_id = f"table-{table_counter}"
            table_counter += 1
            table_ids.append(table_id)

            # rows itself is not deep-copied (same tradeoff as
            # pdf_result_to_normalized above): region["rows"] is produced
            # fresh per extract_excel_tables() call and never reused.
            rows = region["rows"]
            tables.append({
                "table_id": table_id,
                "section_id": section_id,
                "page_range": None,
                "sheet_name": sheet["sheet_name"],
                "num_rows": len(rows),
                "num_cols": max((len(row) for row in rows), default=0),
                "rows": rows,
            })

        sections.append({
            "section_id": section_id,
            "title": sheet["sheet_name"],
            "page_range": None,
            "table_ids": table_ids,
        })

    return {
        "muni_id": muni_id,
        "source_filename": source_filename,
        "pipeline_used": "excel_native",
        "sections": sections,
        "tables": tables,
    }


def write_normalized(processed_dir: Path, normalized: Dict[str, Any]) -> Path:
    """Write a normalized dict as JSON to processed_dir / normalized.json."""
    processed_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = processed_dir / NORMALIZED_FILENAME
    with open(normalized_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    logger.info("Wrote normalized output to %s", normalized_path)
    return normalized_path
