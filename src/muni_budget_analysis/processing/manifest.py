"""
manifest.py

Read/write helpers for per-file processing manifests (manifest.json) produced by
the level-2 file processing pipeline. Tracks provenance, pipeline outcome, and
status for each source budget file processed under processed/{muni_id}/{filename_stem}/.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "manifest.json"


def compute_status(has_output: bool, warnings: List[str]) -> str:
    """Determine processing status from output presence and accumulated warnings."""
    if not has_output:
        return "failed"
    if warnings:
        return "partial"
    return "success"


def build_manifest_record(
    muni_id: int,
    source_filename: str,
    source_sha256: str,
    detected_type: str,
    pipeline_used: Optional[str],
    docling_version: Optional[str],
    page_count: Optional[int],
    warnings: List[str],
    outputs: Dict[str, str],
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a manifest record dict for a single processed source file."""
    status = compute_status(bool(outputs), warnings)
    return {
        "muni_id": muni_id,
        "source_filename": source_filename,
        "source_sha256": source_sha256,
        "detected_type": detected_type,
        "pipeline_used": pipeline_used,
        "docling_version": docling_version,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "page_count": page_count,
        "warnings": warnings.copy(),
        "error": error,
        "outputs": outputs.copy(),
    }


def write_manifest(processed_dir: Path, record: Dict[str, Any]) -> Path:
    """Write a manifest record as JSON to processed_dir / manifest.json."""
    processed_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = processed_dir / MANIFEST_FILENAME
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    logger.info("Wrote manifest to %s", manifest_path)
    return manifest_path


def read_manifest(processed_dir: Path) -> Optional[Dict[str, Any]]:
    """Read a manifest record from processed_dir / manifest.json, or None if absent."""
    manifest_path = processed_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        return None
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)
