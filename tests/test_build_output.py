from muni_budget_analysis.analysis.docling_rows import TableExtract, TableRow
from muni_budget_analysis.analysis.llm_classify import ClassificationResult, RowClassification
from muni_budget_analysis.analysis.build_output import (
    is_percentage_value,
    parse_percentage_val,
    build_records,
    build_line_items_json,
    OutputRecord,
)
from muni_budget_analysis.analysis.resolver import resolve_amount_type, resolve_fiscal_year


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
        "target_year": 2025,
        "table_scopes": [
            {
                "table_id": "table-0",
                "year_axis": "column",
                "rows": [
                    {"index": 1, "row_label": "חינוך", "keep": True},
                    {"index": 2, "row_label": "ספורט", "keep": False},
                ],
                "columns": [
                    {"index": 0, "header": "תקציב 2024", "keep": False, "detected_year": 2024},
                    {"index": 1, "header": "תקציב 2025", "keep": True, "detected_year": 2025},
                ]
            }
        ]
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
    assert records[0].fiscal_year_value == 2025
    assert records[0].amount_type == "budgeted"


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


def test_resolver_heuristics():
    # Test amount_type resolution
    assert resolve_amount_type("הצעת תקציב 2025", "100") == "budgeted"
    assert resolve_amount_type("ביצוע למעשה 2024", "100") == "actual_current_prices"
    assert resolve_amount_type("ביצוע מתואם", "100") == "actual_adjusted_prices"
    assert resolve_amount_type("אחוז גבייה", "85%") == "execution_pct"
    assert resolve_amount_type("שינוי תקציבי", "50") == "change"

    # Test fiscal year resolution
    assert resolve_fiscal_year("תקציב שנת 2026", 2025) == 2026
    assert resolve_fiscal_year("ביצוע למעשה", 2025) == 2025


def test_build_line_items_json():
    codebook = {
        "111": {"label": "ארנונה", "side": "receipts"},
        "6111": {"label": "חינוך", "side": "payments"},
    }
    
    records = [
        OutputRecord(
            source="test",
            table_index=0,
            row_index=1,
            source_label="הכנסות מארנונה",
            matched_code="111",
            matched_label="ארנונה",
            row_type="line_item",
            confidence=0.9,
            note="OK",
            amount_label="תקציב 2025",
            raw_value="1,000",
            amount_ils=1000000.0,
            unit_status="explicit",
            unit_multiplier=1000,
            amount_type="budgeted",
            fiscal_year_value=2025,
        ),
        OutputRecord(
            source="test",
            table_index=0,
            row_index=2,
            source_label="הוצאות חינוך",
            matched_code="6111",
            matched_label="חינוך",
            row_type="line_item",
            confidence=0.9,
            note="OK",
            amount_label="ביצוע 2024",
            raw_value="500",
            amount_ils=500000.0,
            unit_status="explicit",
            unit_multiplier=1000,
            amount_type="actual_current_prices",
            fiscal_year_value=2024,
        ),
        OutputRecord(
            source="test",
            table_index=0,
            row_index=3,
            source_label="כותרת מדור",
            matched_code=None,
            matched_label=None,
            row_type="divider",
            confidence=0.0,
            note="Divider ignored",
            amount_label="",
            raw_value="",
            amount_ils=None,
            unit_status="explicit",
            unit_multiplier=1000,
        )
    ]

    output = build_line_items_json(
        muni_id=901,
        target_year=2025,
        unit="thousands_nis",
        records=records,
        warnings=["Some warnings"],
        codebook_by_code=codebook,
    )

    assert output["muni_id"] == 901
    assert output["fiscal_year"] == 2025
    assert output["unit"] == "thousands_nis"
    assert len(output["line_items"]) == 2  # Divider is ignored!

    item1 = output["line_items"][0]
    assert item1["classification_code"] == "111"
    assert item1["category"] == "income"  # receipts -> income
    assert item1["amount"] == 1000000.0  # pre-normalized!
    assert item1["amount_type"] == "budgeted"
    assert item1["fiscal_year_value"] == 2025

    item2 = output["line_items"][1]
    assert item2["classification_code"] == "6111"
    assert item2["category"] == "expense"  # payments -> expense
    assert item2["amount"] == 500000.0
    assert item2["amount_type"] == "actual_current_prices"
    assert item2["fiscal_year_value"] == 2024


def test_document_fallback_multiplier_resolution():
    from muni_budget_analysis.analysis.run import (
        calculate_table_raw_sum,
        determine_document_fallback_multiplier,
    )

    # 1. Test raw table sum calculation
    table_thousands = TableExtract(
        table_index=0,
        unit="unknown",
        unit_explicit=False,
        unit_evidence=None,
        header_texts=["תקציב"],
        rows=[
            TableRow(row_index=1, label="חינוך", values={"תקציב": "10,000"}),
            TableRow(row_index=2, label="רווחה", values={"תקציב": "5,000"}),
            TableRow(row_index=3, label="ביצוע", values={"ביצוע %": "105%"}),  # should ignore percentages
        ],
    )
    
    assert calculate_table_raw_sum(table_thousands) == 15000.0

    # 2. Test fallback resolution: thousands of NIS
    # Raw total is 15,000 -> 15,000 * 1000 = 15,000,000 (within 5M - 30B)
    mult_thousands = determine_document_fallback_multiplier(
        tables=[table_thousands],
        classification_by_table={},
        scope_data=None,
    )
    assert mult_thousands == 1000

    # 3. Test fallback resolution: full NIS
    # Raw total is 15,000,000 -> 15,000,000 * 1 = 15,000,000 (within 5M - 30B)
    table_full = TableExtract(
        table_index=1,
        unit="unknown",
        unit_explicit=False,
        unit_evidence=None,
        header_texts=["תקציב"],
        rows=[
            TableRow(row_index=1, label="חינוך", values={"תקציב": "10,000,000"}),
            TableRow(row_index=2, label="רווחה", values={"תקציב": "5,000,000"}),
        ],
    )
    mult_full = determine_document_fallback_multiplier(
        tables=[table_full],
        classification_by_table={},
        scope_data=None,
    )
    assert mult_full == 1

    # 4. Test fallback resolution: millions of NIS
    # Raw total is 150 -> 150 * 1,000,000 = 150,000,000 (within 5M - 30B)
    table_millions = TableExtract(
        table_index=2,
        unit="unknown",
        unit_explicit=False,
        unit_evidence=None,
        header_texts=["תקציב"],
        rows=[
            TableRow(row_index=1, label="חינוך", values={"תקציב": "100"}),
            TableRow(row_index=2, label="רווחה", values={"תקציב": "50"}),
        ],
    )
    mult_millions = determine_document_fallback_multiplier(
        tables=[table_millions],
        classification_by_table={},
        scope_data=None,
    )
    assert mult_millions == 1000000

    # 5. Edge case: sum is 0
    table_empty = TableExtract(
        table_index=3,
        unit="unknown",
        unit_explicit=False,
        unit_evidence=None,
        header_texts=["תקציב"],
        rows=[],
    )
    mult_empty = determine_document_fallback_multiplier(
        tables=[table_empty],
        classification_by_table={},
        scope_data=None,
    )
    assert mult_empty == 1000  # defaults to 1000
