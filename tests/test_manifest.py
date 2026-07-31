import sys
import unittest
from pathlib import Path

# Ensure 'src' is in sys.path when running tests directly
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muni_budget_analysis.processing.manifest import (
    compute_status,
    build_manifest_record,
    write_manifest,
    read_manifest,
)


class TestComputeStatus(unittest.TestCase):

    def test_failed_no_output_no_warnings(self):
        self.assertEqual(compute_status(False, []), "failed")

    def test_failed_no_output_with_warnings(self):
        self.assertEqual(compute_status(False, ["x"]), "failed")

    def test_success_output_no_warnings(self):
        self.assertEqual(compute_status(True, []), "success")

    def test_partial_output_with_warnings(self):
        self.assertEqual(compute_status(True, ["x"]), "partial")


def test_write_then_read_manifest_round_trip(tmp_path):
    record = build_manifest_record(
        muni_id=1234,
        source_filename="תקציב.pdf",
        source_sha256="abc123",
        detected_type="pdf_vectored",
        pipeline_used="docling_pdf",
        docling_version="1.0.0",
        page_count=10,
        warnings=[],
        outputs={"normalized": "normalized.json"},
    )
    written_path = write_manifest(tmp_path, record)
    result = read_manifest(tmp_path)
    assert written_path == tmp_path / "manifest.json"
    assert result == record


def test_read_manifest_missing_returns_none(tmp_path):
    result = read_manifest(tmp_path)
    assert result is None


if __name__ == "__main__":
    unittest.main()
