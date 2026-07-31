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
from muni_budget_analysis.analysis.llm_classify import classify_table, DEFAULT_MODEL, classify_tables_batch_async
from muni_budget_analysis.analysis.build_output import build_records, build_line_items_json

logger = logging.getLogger(__name__)


def calculate_table_raw_sum(table) -> float:
    from muni_budget_analysis.analysis.build_output import is_percentage_value, parse_amount
    raw_sum = 0.0
    for row in table.rows:
        for amount_label, raw_value in row.values.items():
            if raw_value is not None and not is_percentage_value(raw_value, amount_label):
                amount = parse_amount(raw_value)
                if amount is not None:
                    raw_sum += abs(amount)
    return raw_sum


def determine_document_fallback_multiplier(tables, classification_by_table, scope_data) -> int:
    from muni_budget_analysis.analysis.build_output import get_table_scope_filters
    
    resolved_total = 0.0
    unresolved_raw_total = 0.0
    
    for table in tables:
        table_keep, _, _, _ = get_table_scope_filters(table, scope_data)
        if not table_keep:
            continue
            
        raw_sum = calculate_table_raw_sum(table)
        
        # Determine if this table already has a resolved multiplier
        multiplier = None
        if table.unit_explicit:
            multiplier = 1000 if table.unit == "thousands" else (1 if table.unit == "full" else 1000)
        else:
            cls = classification_by_table.get(table.table_index)
            if cls and cls.inferred_unit == "thousands":
                multiplier = 1000
            elif cls and cls.inferred_unit == "full":
                multiplier = 1
                
        if multiplier is not None:
            resolved_total += raw_sum * multiplier
        else:
            unresolved_raw_total += raw_sum
            
    if unresolved_raw_total <= 0.0:
        return 1000  # Default fallback
        
    candidates = [1000, 1, 1000000]
    best_multiplier = None
    min_log_distance = float('inf')
    target_center = 387298334.0  # geometric center of [5M, 30B]
    import math
    
    for mult in candidates:
        scaled_doc_total = resolved_total + (unresolved_raw_total * mult)
        if 5000000 <= scaled_doc_total <= 30000000000:
            log_dist = abs(math.log10(scaled_doc_total) - math.log10(target_center))
            if log_dist < min_log_distance:
                min_log_distance = log_dist
                best_multiplier = mult
                
    if best_multiplier is not None:
        return best_multiplier
        
    # If no candidate gets inside the [5M, 30B] range, pick the one closest to the center in log-space
    for mult in candidates:
        scaled_doc_total = resolved_total + (unresolved_raw_total * mult)
        log_dist = abs(math.log10(scaled_doc_total) - math.log10(target_center))
        if log_dist < min_log_distance:
            min_log_distance = log_dist
            best_multiplier = mult
            
    return best_multiplier or 1000


def process_one_document(
    doc_dir: Path,
    api_key: str | None,
    model: str,
    codebook_listing: str,
    codebook_by_code: dict[str, dict],
    force: bool = False,
    processed_dir: Path | None = None,
    analysis_dir: Path | None = None,
) -> bool:
    """Process a single document directory. Returns True if successfully analyzed."""
    normalized_path = doc_dir / "normalized.json"
    manifest_path = doc_dir / "manifest.json"
    scoped_path = doc_dir / "scoped.json"

    # Determine separated output directory
    if processed_dir and analysis_dir:
        try:
            relative_path = doc_dir.relative_to(processed_dir)
            output_dir = analysis_dir / relative_path
        except ValueError:
            output_dir = doc_dir
    else:
        output_dir = doc_dir

    output_path = output_dir / "line_items.json"

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

    # 1. Pre-filter tables and rows BEFORE LLM calling
    from muni_budget_analysis.analysis.build_output import get_table_scope_filters
    from muni_budget_analysis.analysis.llm_classify import ClassificationResult
    
    tables_to_classify = []
    table_configs = []
    
    for table in tables:
        table_keep, rows_to_keep, cols_to_keep, table_scope = get_table_scope_filters(table, scope_data)
        if not table_keep:
            logger.info(f"  Skipping table {table.table_index} entirely (scoped keep is false)")
            continue

        rows_needing_classification = []
        for r in table.rows:
            if not r.values:
                continue
            if r.row_index in rows_to_keep and not rows_to_keep[r.row_index]:
                continue
            rows_needing_classification.append(r)

        if not rows_needing_classification:
            continue

        rows_for_prompt = [
            (r.row_index, r.label, next(iter(r.values.values()), ""))
            for r in rows_needing_classification
        ]
        unit_known = "thousands" if table.unit == "thousands" else None
        
        tables_to_classify.append(table)
        table_configs.append({
            'table_index': table.table_index,
            'codebook_listing': codebook_listing,
            'rows': rows_for_prompt,
            'unit_known': unit_known,
        })

    # 2. Execute classifications concurrently (batch async)
    classification_by_table_index = {}
    if table_configs:
        import asyncio
        
        logger.info(f"  Classifying {len(table_configs)} tables concurrently (batch async)...")
        results = asyncio.run(classify_tables_batch_async(table_configs, api_key=api_key, model=model))
        
        for table_index, result in results:
            if isinstance(result, Exception):
                msg = f"LLM classification failed for table {table_index}: {result!r}"
                warnings.append(msg)
                logger.error(f"  {msg}")
            else:
                classification_by_table_index[table_index] = result

    # Determine document-wide fallback multiplier
    doc_fallback_multiplier = determine_document_fallback_multiplier(
        tables=tables,
        classification_by_table=classification_by_table_index,
        scope_data=scope_data,
    )
    logger.info(f"  Resolved document fallback multiplier: {doc_fallback_multiplier}")

    # 3. Build records using classification results
    for table in tables:
        # Verify table keep scope
        table_keep, _, _, _ = get_table_scope_filters(table, scope_data)
        if not table_keep:
            continue

        result = classification_by_table_index.get(table.table_index)
        if result is None:
            # Fallback to empty classification if omitted/failed
            result = ClassificationResult(rows=[])

        records = build_records(
            source=doc_dir.name,
            table=table,
            classification=result,
            codebook_by_code=codebook_by_code,
            scope_data=scope_data,
            doc_fallback_multiplier=doc_fallback_multiplier,
        )
        all_records.extend(records)

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
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(production_output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"Successfully wrote contract output: {output_path}")
        return True
    except Exception as exc:
        logger.error(f"Failed to write line_items.json for {doc_dir.name}: {exc!r}")
        return False


def run_analysis_batch(
    processed_dir: Path,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    force: bool = False,
    analysis_dir: Path | None = None,
) -> dict[str, int]:
    """Run Level 3 batch analysis over all processed directories under processed_dir."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key and not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        raise RuntimeError("No Gemini/GCP credentials found. Set GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT.")

    if analysis_dir is None:
        if processed_dir.name == "processed":
            analysis_dir = processed_dir.parent / "analysis"
        else:
            analysis_dir = processed_dir / "analysis"

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
            # Determine output directory
            try:
                relative_path = doc_dir.relative_to(processed_dir)
                output_dir = analysis_dir / relative_path
            except ValueError:
                output_dir = doc_dir
            output_path = output_dir / "line_items.json"

            # Check if output exists and we are not forcing
            if output_path.exists() and not force:
                logger.info(f"  Skipping: line_items.json already exists in {output_dir}.")
                skipped += 1
                continue

            success = process_one_document(
                doc_dir=doc_dir,
                api_key=api_key,
                model=model,
                codebook_listing=codebook_listing,
                codebook_by_code=codebook_by_code,
                force=force,
                processed_dir=processed_dir,
                analysis_dir=analysis_dir,
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
    parser.add_argument("--analysis-dir", type=Path, default=None, help="Path to analysis/ output directory")
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
            analysis_dir=args.analysis_dir,
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
