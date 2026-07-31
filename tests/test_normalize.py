import json
import sys
from pathlib import Path

import pytest

# Ensure 'src' is in sys.path when running tests directly
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muni_budget_analysis.processing.excel_pipeline import extract_excel_tables
from muni_budget_analysis.processing.normalize import (
    excel_to_normalized,
    pdf_result_to_normalized,
    write_normalized,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ELAD_XLSX = REPO_ROOT / "budget_examples" / "elad_2022.xlsx"


def _cell(text):
    return {"text": text, "row_span": 1, "col_span": 1, "is_header": False}


def test_pdf_result_to_normalized_wraps_and_adds_sheet_name():
    pdf_result = {
        "sections": [
            {
                "section_id": "sec-0",
                "title": "הכנסות",
                "page_range": [1, 1],
                "table_ids": ["table-0"],
            }
        ],
        "tables": [
            {
                "table_id": "table-0",
                "section_id": "sec-0",
                "page_range": [1, 1],
                "num_rows": 2,
                "num_cols": 2,
                "rows": [
                    [_cell("a"), _cell("b")],
                    [_cell("1"), _cell("2")],
                ],
            }
        ],
        "page_count": 3,
    }

    result = pdf_result_to_normalized(
        pdf_result, muni_id=42, source_filename="foo.pdf", pipeline_used="docling_pdf"
    )

    assert result["muni_id"] == 42
    assert result["source_filename"] == "foo.pdf"
    assert result["pipeline_used"] == "docling_pdf"
    assert result["sections"] == pdf_result["sections"]
    assert result["sections"] is not pdf_result["sections"]  # shallow-copied, not aliased

    assert len(result["tables"]) == 1
    out_table = result["tables"][0]
    assert out_table["sheet_name"] is None
    # Everything else passed through unchanged.
    in_table = pdf_result["tables"][0]
    for key in ("table_id", "section_id", "page_range", "num_rows", "num_cols", "rows"):
        assert out_table[key] == in_table[key]


def test_excel_to_normalized_global_table_ids_and_section_mapping():
    excel_result = {
        "sheets": [
            {
                "sheet_name": "Sheet1",
                "regions": [
                    {"min_row": 1, "rows": [[_cell("a")], [_cell("1")]]},
                    {"min_row": 5, "rows": [[_cell("b"), _cell("c")]]},
                ],
            },
            {
                "sheet_name": "Sheet2",
                "regions": [
                    {"min_row": 1, "rows": [[_cell("x")]]},
                ],
            },
        ]
    }

    result = excel_to_normalized(excel_result, muni_id=7, source_filename="bar.xlsx")

    assert result["muni_id"] == 7
    assert result["source_filename"] == "bar.xlsx"
    assert result["pipeline_used"] == "excel_native"

    assert len(result["sections"]) == 2
    assert len(result["tables"]) == 3

    table_ids = [t["table_id"] for t in result["tables"]]
    assert table_ids == ["table-0", "table-1", "table-2"]

    sec0, sec1 = result["sections"]
    assert sec0["section_id"] == "sec-0"
    assert sec0["title"] == "Sheet1"
    assert sec0["table_ids"] == ["table-0", "table-1"]

    assert sec1["section_id"] == "sec-1"
    assert sec1["title"] == "Sheet2"
    assert sec1["table_ids"] == ["table-2"]

    # Each table's section_id points back to its own sheet's section.
    assert result["tables"][0]["section_id"] == "sec-0"
    assert result["tables"][1]["section_id"] == "sec-0"
    assert result["tables"][2]["section_id"] == "sec-1"

    # page_range is always None for excel tables/sections.
    for table in result["tables"]:
        assert table["page_range"] is None
    for section in result["sections"]:
        assert section["page_range"] is None

    # num_rows/num_cols derived correctly.
    assert result["tables"][0]["num_rows"] == 2
    assert result["tables"][0]["num_cols"] == 1
    assert result["tables"][1]["num_rows"] == 1
    assert result["tables"][1]["num_cols"] == 2
    assert result["tables"][0]["sheet_name"] == "Sheet1"
    assert result["tables"][2]["sheet_name"] == "Sheet2"


def test_write_normalized_round_trip(tmp_path):
    normalized = {
        "muni_id": 1,
        "source_filename": "תקציב.xlsx",
        "pipeline_used": "excel_native",
        "sections": [],
        "tables": [],
    }

    written_path = write_normalized(tmp_path, normalized)

    assert written_path == tmp_path / "normalized.json"
    with open(written_path, "r", encoding="utf-8") as f:
        result = json.load(f)

    assert result == normalized


def test_excel_to_normalized_real_file_smoke():
    assert ELAD_XLSX.exists(), f"missing sample file: {ELAD_XLSX}"

    excel_result = extract_excel_tables(ELAD_XLSX)
    normalized = excel_to_normalized(excel_result, muni_id=99, source_filename="elad_2022.xlsx")

    assert normalized["tables"]
    assert any(table["num_rows"] > 0 for table in normalized["tables"])


if __name__ == "__main__":
    import unittest

    unittest.main()
