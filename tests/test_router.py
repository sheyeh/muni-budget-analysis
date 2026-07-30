import sys
from pathlib import Path

import pytest

# Ensure 'src' is in sys.path when running tests directly
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muni_budget_analysis.processing.router import route

REPO_ROOT = Path(__file__).resolve().parents[1]
BUDGET_EXAMPLES_DIR = REPO_ROOT / "budget_examples"


@pytest.mark.parametrize(
    "detected_type,filename,expected",
    [
        ("pdf", "tel_aviv_2026.pdf", "docling_pdf"),
        ("pdf", "even_yehuda_2025.pdf", "docling_pdf"),
        ("pdf", "mate_yehuda_2024.pdf", "docling_pdf_ocr"),
        ("pdf", "gezer_2026.pdf", "docling_pdf"),
        ("pdf", "lachish_2026.pdf", "docling_pdf_ocr"),
        ("xlsx", "elad_2022.xlsx", "excel_native"),
    ],
)
def test_route_real_files(detected_type, filename, expected):
    local_path = BUDGET_EXAMPLES_DIR / filename
    assert route(detected_type, local_path) == expected


def test_route_unknown_type_returns_none():
    local_path = BUDGET_EXAMPLES_DIR / "tel_aviv_2026.pdf"
    assert route("unknown", local_path) is None
