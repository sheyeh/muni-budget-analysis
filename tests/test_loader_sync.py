import json
import sys
from pathlib import Path

# Ensure 'src' is in sys.path when running tests directly
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muni_budget_analysis.loader.sync import (
    build_budget_row,
    build_line_item_rows,
    derive_status,
    discover_budgets,
    resolve_fiscal_year,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
LEVEL2_DIR = REPO_ROOT / "docs" / "examples" / "level2-processing"


def load_manifest(muni_id: int) -> dict:
    return json.loads((LEVEL2_DIR / str(muni_id) / "manifest.json").read_text(encoding="utf-8"))


def load_line_items(muni_id: int) -> dict:
    return json.loads((LEVEL2_DIR / str(muni_id) / "line_items.json").read_text(encoding="utf-8"))


# --- derive_status ------------------------------------------------------


def test_derive_status_line_items_present_no_warnings():
    line_items_doc = load_line_items(901)
    manifest = load_manifest(901)
    assert derive_status(manifest, line_items_doc) == "processed_success"


def test_derive_status_line_items_present_with_warnings():
    line_items_doc = {"fiscal_year": 2025, "unit": "nis", "line_items": [], "warnings": ["oops"]}
    manifest = {"status": "success"}
    assert derive_status(manifest, line_items_doc) == "processed_partial"


def test_derive_status_no_line_items_manifest_failed():
    manifest = {"status": "failed"}
    assert derive_status(manifest, None) == "processed_failed"


def test_derive_status_no_line_items_manifest_success_is_pending():
    manifest = {"status": "success"}
    assert derive_status(manifest, None) == "pending"


def test_derive_status_no_line_items_manifest_partial_is_pending():
    manifest = {"status": "partial"}
    assert derive_status(manifest, None) == "pending"


# --- resolve_fiscal_year -------------------------------------------------


def test_resolve_fiscal_year_from_line_items():
    line_items_doc = load_line_items(902)
    assert resolve_fiscal_year(LEVEL2_DIR / "902", line_items_doc) == 2024


def test_resolve_fiscal_year_falls_back_to_scoped_json(tmp_path):
    manifest_dir = tmp_path / "906" / "gezer_2026"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "scoped.json").write_text(
        json.dumps({"muni_id": 906, "target_year": 2026}), encoding="utf-8"
    )
    assert resolve_fiscal_year(manifest_dir, None) == 2026


def test_resolve_fiscal_year_none_when_nothing_available(tmp_path):
    manifest_dir = tmp_path / "999" / "unknown"
    manifest_dir.mkdir(parents=True)
    assert resolve_fiscal_year(manifest_dir, None) is None


# --- build_budget_row ------------------------------------------------------


def test_build_budget_row_with_line_items():
    manifest = load_manifest(901)
    line_items_doc = load_line_items(901)
    row = build_budget_row(manifest, line_items_doc, fiscal_year=2025, source_ref="path/to/manifest.json")
    assert row == {
        "muni_id": 901,
        "fiscal_year": 2025,
        "status": "processed_success",
        "unit": "thousands_nis",
        "source_ref": "path/to/manifest.json",
        "processed_at": "2026-07-30T20:52:51.803177+00:00",
    }


def test_build_budget_row_without_line_items_has_no_unit():
    manifest = {"muni_id": 999, "status": "success", "processed_at": "2026-01-01T00:00:00+00:00"}
    row = build_budget_row(manifest, None, fiscal_year=2026, source_ref="path/to/manifest.json")
    assert row["status"] == "pending"
    assert row["unit"] is None


# --- build_line_item_rows -------------------------------------------------


def test_build_line_item_rows_maps_all_fields():
    line_items_doc = {
        "fiscal_year": 2025,
        "unit": "nis",
        "line_items": [
            {
                "classification_code": "631",
                "row_type": "line_item",
                "raw_label_he": "ארנונה כללית (מיסים)",
                "category": "income",
                "fiscal_year_value": 2025,
                "amount_type": "budgeted",
                "amount": 63403000.0,
            }
        ],
        "warnings": [],
    }
    rows = build_line_item_rows(line_items_doc)
    assert rows == [
        {
            "classification_code": "631",
            "row_type": "line_item",
            "raw_label_he": "ארנונה כללית (מיסים)",
            "category": "income",
            "fiscal_year_value": 2025,
            "amount_type": "budgeted",
            "amount": 63403000.0,
        }
    ]


def test_build_line_item_rows_null_amount_passed_through():
    line_items_doc = {
        "fiscal_year": 2026,
        "unit": "nis",
        "line_items": [
            {
                "classification_code": "631",
                "row_type": "line_item",
                "raw_label_he": "% ביצוע",
                "category": "income",
                "fiscal_year_value": 2026,
                "amount_type": "execution_pct",
                "amount": None,
            }
        ],
        "warnings": [],
    }
    rows = build_line_item_rows(line_items_doc)
    assert rows[0]["amount"] is None
    assert rows[0]["amount_type"] == "execution_pct"


def test_build_line_item_rows_against_real_fixture_with_nulls():
    line_items_doc = load_line_items(909)
    rows = build_line_item_rows(line_items_doc)
    assert len(rows) == len(line_items_doc["line_items"])
    null_amounts = [r for r in rows if r["amount"] is None]
    assert len(null_amounts) == 601


def test_build_line_item_rows_empty():
    line_items_doc = load_line_items(903)
    assert build_line_item_rows(line_items_doc) == []


# --- discover_budgets -------------------------------------------------


def test_discover_budgets_two_levels_deep(tmp_path):
    (tmp_path / "901" / "even_yehuda_2025").mkdir(parents=True)
    (tmp_path / "901" / "even_yehuda_2025" / "manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "902" / "mate_yehuda_2024").mkdir(parents=True)
    (tmp_path / "902" / "mate_yehuda_2024" / "manifest.json").write_text("{}", encoding="utf-8")
    # a stray manifest.json one level too shallow must not be picked up
    (tmp_path / "903").mkdir(parents=True)
    (tmp_path / "903" / "manifest.json").write_text("{}", encoding="utf-8")

    found = discover_budgets(tmp_path)

    assert found == sorted(
        [
            tmp_path / "901" / "even_yehuda_2025" / "manifest.json",
            tmp_path / "902" / "mate_yehuda_2024" / "manifest.json",
        ]
    )


def test_discover_budgets_empty_dir(tmp_path):
    assert discover_budgets(tmp_path) == []
