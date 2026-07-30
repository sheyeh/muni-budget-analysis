from pipeline.analysis.docling_rows import TableExtract, TableRow
from pipeline.analysis.llm_classify import ClassificationResult, RowClassification
from pipeline.analysis.build_output import (
    is_percentage_value,
    parse_percentage_val,
    build_records,
    OutputRecord,
)


def test_is_percentage_value():
    assert is_percentage_value("105.29%", "some_header") is True
    assert is_percentage_value(" 85.5 % ", None) is True
    assert is_percentage_value("123", "אחוז ביצוע") is True
    assert is_percentage_value("123", "שיעור הגבייה") is True
    assert is_percentage_value("123", "normal_header") is False
    assert is_percentage_value(None, "normal_header") is False


def test_parse_percentage_val():
    assert parse_percentage_val("105.29%") == 105.29
    assert parse_percentage_val(" 85.5 ") == 85.5
    assert parse_percentage_val("invalid") is None


def test_build_records_percentages():
    table = TableExtract(
        table_index=0,
        unit="thousands",
        unit_explicit=True,
        unit_evidence=None,
        header_texts=["אחוז ביצוע", "תקציב"],
        rows=[
            TableRow(
                row_index=1,
                label="ארנונה",
                values={"אחוז ביצוע": "105.29%", "תקציב": "1,000"},
            )
        ],
    )
    classification = ClassificationResult(
        rows=[
            RowClassification(
                row_index=1,
                code="111",
                row_type="line_item",
                confidence=0.9,
                note="ארנונה כללית",
            )
        ]
    )
    codebook = {"111": {"label": "ארנונה כללית"}}

    records = build_records(
        source="test_source",
        table=table,
        classification=classification,
        codebook_by_code=codebook,
    )

    assert len(records) == 2
    
    # First cell (percentage)
    pct_record = [r for r in records if r.amount_label == "אחוז ביצוע"][0]
    assert pct_record.is_percentage is True
    assert pct_record.parsed_percentage == 105.29
    assert pct_record.amount_ils is None

    # Second cell (regular currency in thousands)
    val_record = [r for r in records if r.amount_label == "תקציב"][0]
    assert val_record.is_percentage is False
    assert val_record.parsed_percentage is None
    assert val_record.amount_ils == 1000000.0


def test_build_records_scope_filtering():
    table = TableExtract(
        table_index=0,
        unit="thousands",
        unit_explicit=True,
        unit_evidence=None,
        header_texts=["תקציב 2024", "תקציב 2025"],
        rows=[
            TableRow(
                row_index=1,
                label="חינוך",
                values={"תקציב 2024": "500", "תקציב 2025": "600"},
            ),
            TableRow(
                row_index=2,
                label="ספורט",
                values={"תקציב 2024": "100", "תקציב 2025": "120"},
            )
        ],
    )
    classification = ClassificationResult(
        rows=[
            RowClassification(row_index=1, code="6111", row_type="line_item", confidence=0.8, note="חינוך"),
            RowClassification(row_index=2, code="6112", row_type="line_item", confidence=0.8, note="ספורט"),
        ]
    )
    codebook = {"6111": {"label": "חינוך"}, "6112": {"label": "ספורט"}}
    
    # We want to keep only row_index=1 (חינוך) and column "תקציב 2025"
    scope_data = {
        "0": {
            "year_axis": "column",
            "rows": [
                {"index": 1, "row_label": "חינוך", "keep": True},
                {"index": 2, "row_label": "ספורט", "keep": False},
            ],
            "columns": [
                {"index": 0, "header": "תקציב 2024", "keep": False},
                {"index": 1, "header": "תקציב 2025", "keep": True},
            ]
        }
    }

    records = build_records(
        source="test_source",
        table=table,
        classification=classification,
        codebook_by_code=codebook,
        scope_data=scope_data,
    )

    # Should only contain 1 record: חינוך for תקציב 2025
    assert len(records) == 1
    assert records[0].row_index == 1
    assert records[0].amount_label == "תקציב 2025"
    assert records[0].amount_ils == 600000.0


def test_validation_warnings():
    table = TableExtract(
        table_index=0,
        unit="full",
        unit_explicit=True,
        unit_evidence=None,
        header_texts=["תקציב"],
        rows=[
            TableRow(
                row_index=1,
                label="נוער",
                values={"תקציב": "100"},
            )
        ],
    )
    # 1. LLM Omitted row classification
    classification_empty = ClassificationResult(rows=[])
    records_empty = build_records(
        source="test_source",
        table=table,
        classification=classification_empty,
        codebook_by_code={},
    )
    assert len(records_empty) == 1
    assert records_empty[0].validation_warning == "LLM omitted row classification"
    assert records_empty[0].row_type == "unresolved"

    # 2. Hallucinated code
    classification_hallucinated = ClassificationResult(
        rows=[
            RowClassification(row_index=1, code="9999", row_type="line_item", confidence=0.7, note="hallucination", unusable_input=True)
        ]
    )
    records_hallucinated = build_records(
        source="test_source",
        table=table,
        classification=classification_hallucinated,
        codebook_by_code={"111": {"label": "valid"}},
    )
    assert len(records_hallucinated) == 1
    assert "Hallucinated code" in records_hallucinated[0].validation_warning
    assert records_hallucinated[0].unusable_input is True
