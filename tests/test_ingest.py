import hashlib
import sys
from pathlib import Path

import pytest

# Ensure 'src' is in sys.path when running tests directly
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muni_budget_analysis.processing.ingest import (
    compute_sha256,
    detect_file_type,
    resolve_source,
    is_already_processed,
)
from muni_budget_analysis.processing.manifest import build_manifest_record, write_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUDGET_EXAMPLES_DIR = REPO_ROOT / "budget_examples"


def test_compute_sha256_known_content(tmp_path):
    content = b"hello muni budget analysis"
    file_path = tmp_path / "sample.txt"
    file_path.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()
    assert compute_sha256(file_path) == expected


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("tel_aviv_2026.pdf", "pdf"),
        ("even_yehuda_2025.pdf", "pdf"),
        ("mate_yehuda_2024.pdf", "pdf"),
        ("gezer_2026.pdf", "pdf"),
        ("elad_2022.xlsx", "xlsx"),
        ("tel_aviv_2026.xlsx", "xlsx"),
    ],
)
def test_detect_file_type_real_files(filename, expected):
    local_path = BUDGET_EXAMPLES_DIR / filename
    assert detect_file_type(local_path) == expected


def test_resolve_source_local_relative_path_does_not_copy(tmp_path):
    raw_dir = tmp_path / "raw"
    relative_value = str(
        (BUDGET_EXAMPLES_DIR / "tel_aviv_2026.pdf").relative_to(REPO_ROOT)
    )
    record = {
        "muni_id": 1,
        "budget_filename": "tel_aviv_2026.pdf",
        "source": {"kind": "local", "value": relative_value},
    }

    result = resolve_source(record, raw_dir)

    assert result == BUDGET_EXAMPLES_DIR / "tel_aviv_2026.pdf"
    assert result.exists()
    assert not raw_dir.exists() or not any(raw_dir.iterdir())


def test_resolve_source_local_missing_file_raises(tmp_path):
    raw_dir = tmp_path / "raw"
    record = {
        "muni_id": 1,
        "budget_filename": "nonexistent.pdf",
        "source": {"kind": "local", "value": "budget_examples/nonexistent.pdf"},
    }

    with pytest.raises(FileNotFoundError):
        resolve_source(record, raw_dir)


def test_is_already_processed_matching_hash(tmp_path):
    processed_dir = tmp_path / "processed"
    target_dir = processed_dir / "1234" / "tel_aviv_2026"
    record = build_manifest_record(
        muni_id=1234,
        source_filename="tel_aviv_2026.pdf",
        source_sha256="abc123",
        detected_type="pdf",
        pipeline_used="docling_pdf",
        docling_version="1.0.0",
        page_count=10,
        warnings=[],
        outputs={"normalized": "normalized.json"},
    )
    write_manifest(target_dir, record)

    assert is_already_processed(processed_dir, 1234, "tel_aviv_2026", "abc123") is True


def test_is_already_processed_different_hash(tmp_path):
    processed_dir = tmp_path / "processed"
    target_dir = processed_dir / "1234" / "tel_aviv_2026"
    record = build_manifest_record(
        muni_id=1234,
        source_filename="tel_aviv_2026.pdf",
        source_sha256="abc123",
        detected_type="pdf",
        pipeline_used="docling_pdf",
        docling_version="1.0.0",
        page_count=10,
        warnings=[],
        outputs={"normalized": "normalized.json"},
    )
    write_manifest(target_dir, record)

    assert is_already_processed(processed_dir, 1234, "tel_aviv_2026", "different_hash") is False


def test_is_already_processed_no_manifest(tmp_path):
    processed_dir = tmp_path / "processed"
    assert is_already_processed(processed_dir, 9999, "no_such_file", "abc123") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
