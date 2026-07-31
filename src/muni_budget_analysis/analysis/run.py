"""
src/muni_budget_analysis/analysis/run.py

Stage 3 Production Batch Runner:
Reads normalized.json and optional scoped.json, processes them through the
Ministry-of-Interior classification pipeline, and outputs standardized line_items.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from muni_budget_analysis.analysis.codebook import load_codebook, as_prompt_listing, by_code
from muni_budget_analysis.analysis.normalized_input import extract_all_normalized_tables
from muni_budget_analysis.analysis.llm_classify import classify_table, DEFAULT_MODEL
from muni_budget_analysis.analysis.build_output import build_records, build_line_items_json

logger = logging.getLogger(__name__)


def process_one_document(
    doc_dir: Path,
    api_key: str | None,
    model: str,
    codebook_listing: str,
    codebook_by_code: dict[str, dict],
    force: bool = False,
) -> bool:
    """Process a single document directory. Returns True if successfully analyzed."""
    normalized_path = doc_dir / "normalized.json"
    manifest_path = doc_dir / "manifest.json"
    scoped_path = doc_dir / "scoped.json"
    output_path = doc_dir / "line_items.json"

    if not normalized_path.exists():
        logger.warning(f"Skipping {doc_dir.name}: normalized.json does not exist.")
        return False

    if output_path.exists() and not force:
        logger.info(f"Skipping {doc_dir.name}: line_items.json already exists (use --force to overwrite).")
        return True

    # 1. Read manifest.json first
    muni_id = 901  # fallback default
    target_year = 2025  # fallback default
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("status") == "failed":
                logger.warning(f"Skipping {doc_dir.name}: manifest status is failed.")
                return False
            muni_id = manifest.get("muni_id", muni_id)
        except Exception as exc:
            logger.warning(f"Failed to read manifest.json for {doc_dir.name}: {exc!r}")

    # 2. Read scoped.json (Stage 2.5) if present
    scope_data = None
    if scoped_path.is_file():
        try:
            scope_data = json.loads(scoped_path.read_text(encoding="utf-8"))
            logger.info(f"Loaded scope data from: {scoped_path.name}")
            target_year = scope_data.get("target_year", target_year)
            muni_id = scope_data.get("muni_id", muni_id)
        except Exception as exc:
            logger.warning(f"Failed to read scoped.json for {doc_dir.name}: {exc!r}")

    # 3. Read normalized.json
    try:
        normalized_doc = json.loads(normalized_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error(f"Failed to read normalized.json for {doc_dir.name}: {exc!r}")
        return False

    tables = extract_all_normalized_tables(normalized_doc)
    all_records = []
    warnings: list[str] = []

    logger.info(f"Processing {len(tables)} tables in {doc_dir.name} (muni_id={muni_id}, target_year={target_year})...")

    for table in tables:
        rows_needing_classification = [r for r in table.rows if r.values]
        if not rows_needing_classification:
            continue

        rows_for_prompt = [
            (r.row_index, r.label, next(iter(r.values.values()), ""))
            for r in rows_needing_classification
        ]
        unit_known = "thousands" if table.unit == "thousands" else None

        logger.info(f"  Classifying table {table.table_index}: {len(rows_for_prompt)} rows")

        try:
            result = classify_table(
                codebook_listing=codebook_listing,
                rows=rows_for_prompt,
                unit_known=unit_known,
                api_key=api_key,
                model=model,
            )
        except Exception as exc:
            msg = f"LLM classification failed for table {table.table_index}: {exc!r}"
            warnings.append(msg)
            logger.error(f"  {msg}")
            continue

        records = build_records(
            source=doc_dir.name,
            table=table,
            classification=result,
            codebook_by_code=codebook_by_code,
            scope_data=scope_data,
        )
        all_records.extend(records)
        time.sleep(1.0)  # Rate limiting safety cushion

    # 4. Construct production contract
    unit_str = "thousands_nis" if any(r.unit_multiplier == 1000 for r in all_records) else "nis"
    production_output = build_line_items_json(
        muni_id=muni_id,
        target_year=target_year,
        unit=unit_str,
        records=all_records,
        warnings=warnings,
        codebook_by_code=codebook_by_code,
    )

    try:
        output_path.write_text(
            json.dumps(production_output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"Successfully wrote contract output: {output_path.name}")
        return True
    except Exception as exc:
        logger.error(f"Failed to write line_items.json for {doc_dir.name}: {exc!r}")
        return False


def run_analysis_batch(
    processed_dir: Path,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    force: bool = False,
) -> dict[str, int]:
    """Run Level 3 batch analysis over all processed directories under processed_dir."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key and not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        raise RuntimeError("No Gemini/GCP credentials found. Set GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT.")

    codebook = load_codebook()
    codebook_listing = as_prompt_listing(codebook)
    codebook_by_code = by_code(codebook)

    doc_dirs = sorted(
        p for p in processed_dir.glob("*/*") if (p / "normalized.json").exists()
    )
    logger.info(f"Found {len(doc_dirs)} processed document(s) under {processed_dir}")

    succeeded = 0
    skipped = 0
    failed = 0

    for doc_dir in doc_dirs:
        logger.info(f"=== Analyzing {doc_dir.relative_to(processed_dir)} ===")
        try:
            # Check if output exists and we are not forcing
            if (doc_dir / "line_items.json").exists() and not force:
                logger.info("  Skipping: line_items.json already exists.")
                skipped += 1
                continue

            success = process_one_document(
                doc_dir=doc_dir,
                api_key=api_key,
                model=model,
                codebook_listing=codebook_listing,
                codebook_by_code=codebook_by_code,
                force=force,
            )
            if success:
                succeeded += 1
            else:
                failed += 1
        except Exception as exc:
            logger.error(f"  Document analysis failed critically: {exc!r}")
            failed += 1

    return {"succeeded": succeeded, "skipped": skipped, "failed": failed}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stage 3 category classification & normalization over processed files")
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"), help="Path to processed/ directory")
    parser.add_argument("--api-key", default=None, help="Gemini API Key")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name")
    parser.add_argument("--force", action="store_true", help="Overwrite existing line_items.json")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    try:
        stats = run_analysis_batch(
            processed_dir=args.processed_dir,
            api_key=args.api_key,
            model=args.model,
            force=args.force,
        )
        print(f"\n=== Level 3 Classification & Normalization Complete ===")
        print(f"Succeeded: {stats['succeeded']}")
        print(f"Skipped:   {stats['skipped']}")
        print(f"Failed:    {stats['failed']}")
        return 0
    except Exception as exc:
        print(f"Critical execution error: {exc!r}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
