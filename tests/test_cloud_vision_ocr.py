import sys
from pathlib import Path

import pytest

# Ensure 'src' is in sys.path when running tests directly
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from docling.datamodel.pipeline_options import OcrMode
from docling.models.factories import get_ocr_factory

from muni_budget_analysis.processing.cloud_vision_ocr import (
    CloudVisionOcrOptions,
    register_cloud_vision_ocr,
)
from muni_budget_analysis.processing.pdf_pipeline import build_ocr_options

# These only exercise the wiring (options construction + OCR-factory
# registration) -- no live Cloud Vision calls, no credentials needed. The
# actual OCR path was verified manually end-to-end against
# mate_yehuda_2024.pdf (the "מפעל המים" row Tesseract garbled, per
# docs/examples/gcp_vision/README.md, comes back correct via this backend).


def test_build_ocr_options_cloud_vision_returns_full_page_hebrew_options():
    options = build_ocr_options("cloud_vision")

    assert isinstance(options, CloudVisionOcrOptions)
    assert options.mode == OcrMode.FULL_PAGE
    assert "he" in options.lang


def test_build_ocr_options_unknown_backend_still_raises():
    with pytest.raises(ValueError):
        build_ocr_options("not_a_real_backend")


def test_register_cloud_vision_ocr_is_idempotent_and_visible_to_default_factory():
    register_cloud_vision_ocr()
    register_cloud_vision_ocr()  # must not raise on the second call

    factory = get_ocr_factory(allow_external_plugins=False)
    assert "cloud_vision" in factory.registered_kind
