import sys
from pathlib import Path

import pytest

# Ensure 'src' is in sys.path when running tests directly
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from docling.datamodel.pipeline_options import TableFormerMode
from docling_core.types.doc.document import DoclingDocument, TableData

from muni_budget_analysis.processing.pdf_pipeline import (
    _assemble_group_rows,
    convert_pdf,
    make_converter,
    merge_multipage_tables,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BUDGET_EXAMPLES_DIR = REPO_ROOT / "budget_examples"

# FAST mode (not ACCURATE) to keep the dev-loop test fast -- both sample
# files are small (1pp and 3pp). Table shape (num_cols) was re-verified
# empirically against FAST mode output, not assumed to match the
# ACCURATE-mode numbers documented in docs/examples/docling/README.md.
TABLE_MODE = TableFormerMode.FAST


def test_convert_pdf_even_yehuda_text_layer():
    """
    even_yehuda_2025.pdf: per docs/examples/docling/README.md, 1 table
    (9-column budget detail table, ~40 rows). Real fidelity check, not just
    non-empty.
    """
    path = BUDGET_EXAMPLES_DIR / "even_yehuda_2025.pdf"
    result = convert_pdf(path, pipeline_used="docling_pdf", table_mode=TABLE_MODE)

    assert len(result["tables"]) == 1
    table = result["tables"][0]
    assert table["num_rows"] > 0
    assert table["num_cols"] == 9
    assert result["page_count"] > 0


def test_convert_pdf_mate_yehuda_ocr_does_not_merge_distinct_tables():
    """
    mate_yehuda_2024.pdf: per docs/examples/docling/README.md, 2 tables
    (income table, expense table) adjacent with no heading between them
    (only a picture). This is the critical regression test for the
    header-row-equality merge guard in merge_multipage_tables(): without
    it, the naive "no heading between" grouping would wrongly merge these
    two distinct tables (different header rows) into 1.
    """
    path = BUDGET_EXAMPLES_DIR / "mate_yehuda_2024.pdf"
    result = convert_pdf(path, pipeline_used="docling_pdf_ocr", table_mode=TABLE_MODE)

    assert len(result["tables"]) == 2
    for table in result["tables"]:
        assert table["num_rows"] > 0
        assert table["num_cols"] > 0


def _add_table(doc: DoclingDocument, rows: list) -> None:
    """
    Add a real TableItem (built through DoclingDocument.add_table /
    TableData.add_rows -- not a mock) with the given rows, each a list of
    cell-text strings. All rows must be the same length.
    """
    data = TableData(num_rows=0, num_cols=len(rows[0]))
    data.add_rows(rows)
    doc.add_table(data=data)


def test_merge_multipage_tables_merges_continuation_with_matching_header():
    """
    Two adjacent tables sharing an identical header row, with no heading
    item between them, are a genuine multi-page continuation and must be
    merged into a single group -- this is the actual merge path
    (len(group) > 1) that neither pre-existing test exercises.
    """
    doc = DoclingDocument(name="synthetic-merge")
    _add_table(doc, [["קוד", "סכום"], ["100", "5000"]])
    _add_table(doc, [["קוד", "סכום"], ["200", "6000"]])

    groups = merge_multipage_tables(doc)

    assert len(groups) == 1
    assert len(groups[0]) == 2

    # Regression check for the just-fixed bug: the merged row assembly must
    # NOT duplicate the header row -- exactly 1 header + 2 data rows.
    rows = _assemble_group_rows(groups[0])
    assert len(rows) == 3
    assert [c["text"] for c in rows[0]] == ["קוד", "סכום"]
    assert [c["text"] for c in rows[1]] == ["100", "5000"]
    assert [c["text"] for c in rows[2]] == ["200", "6000"]


def test_merge_multipage_tables_heading_between_prevents_merge():
    """
    Same matching-header setup as above, but with a SectionHeaderItem
    between the two tables -- header-text equality alone is not enough to
    merge; a heading in between must keep them as separate groups.
    """
    doc = DoclingDocument(name="synthetic-no-merge")
    _add_table(doc, [["קוד", "סכום"], ["100", "5000"]])
    doc.add_heading("New Section")
    _add_table(doc, [["קוד", "סכום"], ["200", "6000"]])

    groups = merge_multipage_tables(doc)

    assert len(groups) == 2
    assert len(groups[0]) == 1
    assert len(groups[1]) == 1


def test_merge_multipage_tables_runs_on_single_table_doc():
    """
    even_yehuda_2025.pdf has exactly 1 table, so there are trivially no
    merge candidates -- this just confirms merge_multipage_tables() runs
    without error on a doc with a single table and returns it as its own
    group.
    """
    path = BUDGET_EXAMPLES_DIR / "even_yehuda_2025.pdf"
    converter = make_converter(force_ocr=False, table_mode=TABLE_MODE)
    result = converter.convert(str(path))
    doc = result.document

    groups = merge_multipage_tables(doc)

    assert len(groups) == 1
    assert len(groups[0]) == 1
