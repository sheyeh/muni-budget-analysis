"""
ingest.py

Resolves a level-1 input record ({muni_id, budget_filename, source: {kind, value}}) to a
local file on disk, computes its content hash, sniffs its real file type via magic bytes,
and decides whether it's already been processed (cache-by-hash) before the rest of the
level-2 pipeline (router.py, pdf_pipeline.py, excel_pipeline.py) touches it.
"""

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict

import requests

from .manifest import read_manifest

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

CHUNK_SIZE = 8192


def compute_sha256(path: Path) -> str:
    """Compute the sha256 hexdigest of a file via a streaming read."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_file_type(path: Path) -> str:
    """Detect a file's real type from its magic bytes (never trust the extension)."""
    import filetype

    kind = filetype.guess(str(path))
    if kind is None:
        return "unknown"
    extension_map = {
        "pdf": "pdf",
        "xlsx": "xlsx",
        "xls": "xls",
    }
    return extension_map.get(kind.extension, "unknown")


def resolve_source(record: Dict[str, Any], raw_dir: Path) -> Path:
    """Resolve a level-1 input record's source to a local file path."""
    source = record["source"]
    kind = source["kind"]

    if kind == "url":
        muni_dir = raw_dir / str(record["muni_id"])
        destination_path = muni_dir / record["budget_filename"]
        if destination_path.exists():
            logger.info("Already downloaded, skipping fetch: %s", destination_path)
            return destination_path
        muni_dir.mkdir(parents=True, exist_ok=True)
        url = source["value"]
        logger.info("Downloading %s to %s", url, destination_path)
        response = requests.get(url, timeout=60, stream=True)
        response.raise_for_status()
        with open(destination_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                f.write(chunk)
        return destination_path

    if kind == "local":
        local_path = Path(source["value"])
        if not local_path.is_absolute():
            local_path = PROJECT_ROOT / local_path
        if not local_path.exists():
            raise FileNotFoundError(f"Local source file not found: {local_path}")
        return local_path

    raise ValueError(f"Unrecognized source kind: {kind!r}")


def output_dir_key(filename: str) -> str:
    """Collision-safe output-dir key: stem + extension, so files that share a
    stem but differ in extension (e.g. tel_aviv_2026.pdf vs .xlsx) don't
    collide under the same muni_id."""
    path = Path(filename)
    return f"{path.stem}_{path.suffix.lstrip('.')}" if path.suffix else path.stem


def is_already_processed(
    processed_dir: Path, muni_id: int, output_key: str, source_sha256: str
) -> bool:
    """Check whether a file with this content hash already has a manifest on disk."""
    target_dir = processed_dir / str(muni_id) / output_key
    existing = read_manifest(target_dir)
    return existing is not None and existing.get("source_sha256") == source_sha256


def ingest(record: Dict[str, Any], raw_dir: Path, processed_dir: Path) -> Dict[str, Any]:
    """Resolve, hash, and type-detect a level-1 record; report whether it's already processed."""
    local_path = resolve_source(record, raw_dir)
    source_sha256 = compute_sha256(local_path)
    detected_type = detect_file_type(local_path)
    key = output_dir_key(record["budget_filename"])
    skip = is_already_processed(processed_dir, record["muni_id"], key, source_sha256)
    return {
        "local_path": local_path,
        "source_sha256": source_sha256,
        "detected_type": detected_type,
        "output_key": key,
        "skip": skip,
    }
