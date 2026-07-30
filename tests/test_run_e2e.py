"""
End-to-end verification for the level-2 file processing pipeline.

prd.md's Task 7 literally asks to verify against tel_aviv_2026.pdf,
even_yehuda_2025.pdf, and mate_yehuda_2024.pdf, including a Tel
Aviv-specific check that code 631 maps to
19,640,900 / 20,000,000 / 20,000,000. This test deliberately narrows that
to a CPU-fast subset -- "Tier A" -- per the approved implementation plan
(.claude/plans/piped-noodling-ocean.md, "## Verification" section, written
during planning for this exact reason: tel_aviv_2026.pdf's 364 pages need
GPU/take hours on CPU in ACCURATE mode). even_yehuda_2025.pdf and
mate_yehuda_2024.pdf are kept from the original 3; elad_2022.xlsx
substitutes for tel_aviv_2026.pdf here to also exercise the Excel path.

"Tier B" (same plan doc) is the still-outstanding piece this test does NOT
cover: running tel_aviv_2026.pdf (and shafir_2026.pdf) through this same
run_batch() on a GCP T4 GPU VM (scripts/gcp_gpu_spike.sh) and checking the
code-631 cells, reproducing the Task 0 spike's finding through the
production pipeline. Not automated here -- it costs real GCP VM time and
needs an explicit go-ahead, tracked as a follow-up rather than run as part
of this change.
"""

import json
import sys
from pathlib import Path

import pytest

# Ensure 'src' is in sys.path when running tests directly
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from docling.datamodel.pipeline_options import TableFormerMode

from muni_budget_analysis.processing import run as run_module
from muni_budget_analysis.processing.run import process_one, run_batch

REPO_ROOT = Path(__file__).resolve().parents[1]
BUDGET_EXAMPLES_DIR = REPO_ROOT / "budget_examples"

# muni_id values below (901/902/903) are synthetic placeholders for this
# test only -- NOT real semel-yishuv (municipality) codes.
SYNTHETIC_MANIFEST = [
    {
        "muni_id": 901,
        "budget_filename": "even_yehuda_2025.pdf",
        "source": {
            "kind": "local",
            "value": str((BUDGET_EXAMPLES_DIR / "even_yehuda_2025.pdf").relative_to(REPO_ROOT)),
        },
    },
    {
        "muni_id": 902,
        "budget_filename": "mate_yehuda_2024.pdf",
        "source": {
            "kind": "local",
            "value": str((BUDGET_EXAMPLES_DIR / "mate_yehuda_2024.pdf").relative_to(REPO_ROOT)),
        },
    },
    {
        "muni_id": 903,
        "budget_filename": "elad_2022.xlsx",
        "source": {
            "kind": "local",
            "value": str((BUDGET_EXAMPLES_DIR / "elad_2022.xlsx").relative_to(REPO_ROOT)),
        },
    },
]


@pytest.fixture(autouse=True)
def fast_table_mode(monkeypatch):
    """
    Use TableFormerMode.FAST (not ACCURATE) for this test's docling
    conversions to keep the dev-loop fast, matching tests/test_pdf_pipeline.py's
    convention. Both PDF samples here are small (1pp and 3pp).
    """
    monkeypatch.setattr(run_module, "TABLE_MODE", TableFormerMode.FAST)


@pytest.fixture(autouse=True)
def tesseract_ocr_backend(monkeypatch):
    """
    Force run.py's OCR_BACKEND back to "tesseract" for this test. run.py's
    real default is "cloud_vision" (issue #4) which calls the live Cloud
    Vision API over the network with Application Default Credentials -- not
    something this test suite should depend on being configured. The
    cloud_vision backend itself is covered by tests/test_cloud_vision_ocr.py
    (wiring, no live calls) and manually verified end-to-end against
    mate_yehuda_2024.pdf.
    """
    monkeypatch.setattr(run_module, "OCR_BACKEND", "tesseract")


def test_run_batch_produces_populated_normalized_json_for_all_three_samples(tmp_path):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    level1_manifest_path = tmp_path / "level1_manifest.json"
    with open(level1_manifest_path, "w", encoding="utf-8") as f:
        json.dump(SYNTHETIC_MANIFEST, f, ensure_ascii=False, indent=2)

    results = run_batch(level1_manifest_path, raw_dir, processed_dir)

    assert len(results) == 3

    for manifest_record, source_record in zip(results, SYNTHETIC_MANIFEST):
        assert manifest_record["status"] == "success", manifest_record
        assert manifest_record["warnings"] == []
        assert manifest_record["error"] is None

        normalized_filename = manifest_record["outputs"]["normalized"]
        normalized_path = (
            processed_dir
            / str(source_record["muni_id"])
            / Path(source_record["budget_filename"]).stem
            / normalized_filename
        )
        assert normalized_path.exists()

        with open(normalized_path, "r", encoding="utf-8") as f:
            normalized = json.load(f)

        assert normalized["tables"], f"no tables extracted for {source_record['budget_filename']}"
        for table in normalized["tables"]:
            assert table["num_rows"] > 0, (
                f"table {table['table_id']} in {source_record['budget_filename']} has "
                f"num_rows={table['num_rows']}"
            )


def test_process_one_nonexistent_local_file_does_not_raise(tmp_path):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    record = {
        "muni_id": 999,
        "budget_filename": "does_not_exist.pdf",
        "source": {"kind": "local", "value": "budget_examples/does_not_exist.pdf"},
    }

    result = process_one(record, raw_dir, processed_dir)

    assert result["status"] == "failed"
    assert result["error"] is not None
    assert result["outputs"] == {}
