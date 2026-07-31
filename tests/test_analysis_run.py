"""
tests/test_analysis_run.py

Integration and unit tests for the Level 3 production batch runner (src/muni_budget_analysis/analysis/run.py).
Mocks Gemini API classification calls to avoid network dependency and costs.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from muni_budget_analysis.analysis.run import run_analysis_batch, process_one_document
from muni_budget_analysis.analysis.llm_classify import ClassificationResult, RowClassification


@pytest.fixture
def mock_codebook(tmp_path, monkeypatch):
    """Provide a minimal mock codebook for the runner."""
    codebook_data = [
        {"code": "111", "label": "ארנונה מגורים", "side": "receipts"},
        {"code": "6111", "label": "שכר מורים", "side": "payments"},
    ]
    codebook_file = tmp_path / "mock_moi_codes.json"
    codebook_file.write_text(json.dumps(codebook_data, ensure_ascii=False), encoding="utf-8")
    
    # Patch default path inside codebook.py
    import muni_budget_analysis.analysis.codebook as cb
    monkeypatch.setattr(cb, "DEFAULT_PATH", codebook_file)
    return codebook_file


@pytest.fixture
def sample_normalized_json():
    """Minimal schema-conformant normalized.json content."""
    return {
        "muni_id": 901,
        "source_filename": "even_yehuda_2025.pdf",
        "sections": [
            {"section_id": "sec-1", "title": "הכנסות עצמיות"}
        ],
        "tables": [
            {
                "table_id": "table-0",
                "section_id": "sec-1",
                "num_cols": 2,
                "num_rows": 2,
                "rows": [
                    [
                        {"text": "תיאור סעיף", "is_header": True},
                        {"text": "תקציב 2025", "is_header": True}
                    ],
                    [
                        {"text": "ארנונה", "is_header": False},
                        {"text": "1,000", "is_header": False}
                    ]
                ]
            }
        ]
    }


@pytest.fixture
def sample_manifest_json():
    """Standard Level 2 pipeline manifest.json content."""
    return {
        "muni_id": 901,
        "source_filename": "even_yehuda_2025.pdf",
        "status": "success",
        "warnings": [],
        "error": None,
        "outputs": {
            "normalized": "normalized.json"
        }
    }


@pytest.fixture
def sample_scoped_json():
    """Provisional Level 2.5 scoped.json content."""
    return {
        "muni_id": 901,
        "source_filename": "even_yehuda_2025.pdf",
        "target_year": 2025,
        "tables_total": 1,
        "tables_classified": 1,
        "table_scopes": [
            {
                "table_id": "table-0",
                "year_axis": "column",
                "rows": [
                    {"index": 1, "row_label": "ארנונה", "keep": True}
                ],
                "columns": [
                    {"index": 0, "header": "תקציב 2025", "keep": True, "detected_year": 2025}
                ]
            }
        ]
    }


@patch("muni_budget_analysis.analysis.run.classify_table")
def test_process_one_document_success(
    mock_classify,
    tmp_path,
    mock_codebook,
    sample_normalized_json,
    sample_manifest_json,
    sample_scoped_json,
):
    # Setup directories
    doc_dir = tmp_path / "901" / "even_yehuda_2025_pdf"
    doc_dir.mkdir(parents=True)

    (doc_dir / "normalized.json").write_text(json.dumps(sample_normalized_json, ensure_ascii=False), encoding="utf-8")
    (doc_dir / "manifest.json").write_text(json.dumps(sample_manifest_json, ensure_ascii=False), encoding="utf-8")
    (doc_dir / "scoped.json").write_text(json.dumps(sample_scoped_json, ensure_ascii=False), encoding="utf-8")

    # Mock the LLM classification return
    mock_classify.return_value = ClassificationResult(
        rows=[
            RowClassification(row_index=1, code="111", row_type="line_item", confidence=0.95, note="matched successfully")
        ]
    )

    from muni_budget_analysis.analysis.codebook import load_codebook, as_prompt_listing, by_code
    codebook = load_codebook()
    codebook_listing = as_prompt_listing(codebook)
    codebook_by_code = by_code(codebook)

    # Execute
    res = process_one_document(
        doc_dir=doc_dir,
        api_key="fake-key",
        model="fake-model",
        codebook_listing=codebook_listing,
        codebook_by_code=codebook_by_code,
        force=False
    )

    assert res is True
    assert mock_classify.called

    # Check output
    output_file = doc_dir / "line_items.json"
    assert output_file.exists()
    
    line_items_data = json.loads(output_file.read_text(encoding="utf-8"))
    assert line_items_data["muni_id"] == 901
    assert line_items_data["fiscal_year"] == 2025
    assert len(line_items_data["line_items"]) == 1
    
    item = line_items_data["line_items"][0]
    assert item["classification_code"] == "111"
    assert item["row_type"] == "line_item"
    assert item["raw_label_he"] == "ארנונה"
    assert item["category"] == "income"  # "111" has side "receipts" -> "income"
    assert item["fiscal_year_value"] == 2025


@patch("muni_budget_analysis.analysis.run.classify_table")
def test_process_one_document_skips_failed_manifest(
    mock_classify,
    tmp_path,
    mock_codebook,
    sample_normalized_json,
    sample_manifest_json,
):
    doc_dir = tmp_path / "901" / "even_yehuda_2025_pdf"
    doc_dir.mkdir(parents=True)

    # Manifest marked as failed
    sample_manifest_json["status"] = "failed"

    (doc_dir / "normalized.json").write_text(json.dumps(sample_normalized_json, ensure_ascii=False), encoding="utf-8")
    (doc_dir / "manifest.json").write_text(json.dumps(sample_manifest_json, ensure_ascii=False), encoding="utf-8")

    from muni_budget_analysis.analysis.codebook import load_codebook, as_prompt_listing, by_code
    codebook = load_codebook()
    codebook_listing = as_prompt_listing(codebook)
    codebook_by_code = by_code(codebook)

    res = process_one_document(
        doc_dir=doc_dir,
        api_key="fake-key",
        model="fake-model",
        codebook_listing=codebook_listing,
        codebook_by_code=codebook_by_code,
        force=False
    )

    assert res is False
    assert not mock_classify.called
    assert not (doc_dir / "line_items.json").exists()


@patch("muni_budget_analysis.analysis.run.classify_table")
def test_run_analysis_batch(
    mock_classify,
    tmp_path,
    mock_codebook,
    sample_normalized_json,
    sample_manifest_json,
):
    # Set up processed directory layout:
    # 901/even_yehuda_2025_pdf/normalized.json
    # 902/unnormalized_folder/manifest.json (No normalized.json -> should be skipped)
    processed_dir = tmp_path / "processed"
    
    doc_dir_1 = processed_dir / "901" / "even_yehuda_2025_pdf"
    doc_dir_1.mkdir(parents=True)
    (doc_dir_1 / "normalized.json").write_text(json.dumps(sample_normalized_json, ensure_ascii=False), encoding="utf-8")
    (doc_dir_1 / "manifest.json").write_text(json.dumps(sample_manifest_json, ensure_ascii=False), encoding="utf-8")

    doc_dir_2 = processed_dir / "902" / "no_normalized_here"
    doc_dir_2.mkdir(parents=True)
    (doc_dir_2 / "manifest.json").write_text(json.dumps(sample_manifest_json, ensure_ascii=False), encoding="utf-8")

    mock_classify.return_value = ClassificationResult(
        rows=[
            RowClassification(row_index=1, code="111", row_type="line_item", confidence=0.8, note="matched")
        ]
    )

    # Run the batch analysis
    stats = run_analysis_batch(
        processed_dir=processed_dir,
        api_key="fake-key",
        model="fake-model",
        force=False
    )

    assert stats["succeeded"] == 1
    assert stats["skipped"] == 0
    assert stats["failed"] == 0  # doc_dir_2 has no normalized.json, so it's excluded from doc_dirs discovery list completely

    assert (doc_dir_1 / "line_items.json").exists()
    assert not (doc_dir_2 / "line_items.json").exists()
