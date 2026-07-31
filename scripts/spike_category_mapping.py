"""
scripts/spike_category_mapping.py

Stage-3 category classification and unit normalization.
Supports both the legacy Docling native.json and the production Level 2/2.5 handshake
normalized.json + scoped.json + manifest.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.analysis.build_output import build_records, records_to_dicts, build_line_items_json
from pipeline.analysis.codebook import as_prompt_listing, by_code, load_codebook
from pipeline.analysis.docling_rows import extract_all_tables
from pipeline.analysis.normalized_input import extract_all_normalized_tables
from pipeline.analysis.llm_classify import classify_table


def process_one(
    source: str,
    input_path: Path,
    codebook_listing: str,
    codebook_by_code: dict,
    api_key: str,
    model: str,
) -> tuple[list[dict], dict | None]:
    # 1. Read manifest.json first if we are in a standardized directory
    manifest_path = input_path.parent / "manifest.json"
    muni_id = 901  # default fallback
    target_year = 2025  # default fallback
    
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("status") == "failed":
                print(f"  Skipping {source}: manifest status is 'failed'.")
                return [], None
            muni_id = manifest.get("muni_id", muni_id)
        except Exception as exc:
            print(f"  Warning: failed to load manifest.json: {exc!r}")

    doc = json.loads(input_path.read_text(encoding="utf-8"))
    
    # 2. Load scoped.json if present
    scoped_path = input_path.parent / "scoped.json"
    scope_data = None
    if scoped_path.is_file():
        try:
            scope_data = json.loads(scoped_path.read_text(encoding="utf-8"))
            print(f"  Loaded scope filtering metadata from: {scoped_path.name}")
            target_year = scope_data.get("target_year", target_year)
            muni_id = scope_data.get("muni_id", muni_id)
        except Exception as exc:
            print(f"  Warning: failed to load scoped.json: {exc!r}")

    # Determine whether input is normalized.json or legacy native.json
    is_normalized = "sections" in doc and "tables" in doc and len(doc["tables"]) > 0 and "rows" in doc["tables"][0] and isinstance(doc["tables"][0]["rows"], list) and (len(doc["tables"][0]["rows"]) == 0 or isinstance(doc["tables"][0]["rows"][0], list))

    if is_normalized:
        print(f"  Detected production normalized.json input format.")
        tables = extract_all_normalized_tables(doc)
    else:
        print(f"  Detected legacy native.json docling input format.")
        tables = extract_all_tables(doc)

    all_records = []
    warnings = []

    for table in tables:
        rows_needing_classification = [r for r in table.rows if r.values]
        if not rows_needing_classification:
            continue

        rows_for_prompt = [
            (r.row_index, r.label, next(iter(r.values.values()), ""))
            for r in rows_needing_classification
        ]
        unit_known = "thousands" if table.unit == "thousands" else None

        print(
            f"  table {table.table_index}: {len(rows_for_prompt)} rows, "
            f"unit={'explicit thousands' if unit_known else 'unknown -> asking LLM'}"
        )
        
        try:
            result = classify_table(
                codebook_listing=codebook_listing,
                rows=rows_for_prompt,
                unit_known=unit_known,
                api_key=api_key,
                model=model,
            )
        except Exception as exc:
            warnings.append(f"LLM classification failed for table {table.table_index}: {exc!r}")
            print(f"    WARNING: LLM classification failed: {exc!r}")
            continue

        if not table.unit_explicit and result.inferred_unit:
            print(
                f"    LLM inferred unit={result.inferred_unit} "
                f"(confidence={result.inferred_unit_confidence}): {result.inferred_unit_rationale}"
            )

        records = build_records(
            source=source,
            table=table,
            classification=result,
            codebook_by_code=codebook_by_code,
            scope_data=scope_data,
        )
        all_records.extend(records)

    # Convert to OutputRecord dicts
    legacy_dicts = records_to_dicts(all_records)
    
    # 3. Construct production line_items.json format
    unit_str = "thousands_nis" if any(r.unit_multiplier == 1000 for r in all_records) else "nis"
    production_output = build_line_items_json(
        muni_id=muni_id,
        target_year=target_year,
        unit=unit_str,
        records=all_records,
        warnings=warnings,
        codebook_by_code=codebook_by_code,
    )

    # 4. Write line_items.json back to the input's folder
    line_items_out_path = input_path.parent / "line_items.json"
    try:
        line_items_out_path.write_text(
            json.dumps(production_output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  Successfully wrote contract output: {line_items_out_path.name}")
    except Exception as exc:
        print(f"  Warning: failed to write line_items.json to {input_path.parent}: {exc!r}")

    return legacy_dicts, production_output


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api-key", default=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"), help="Gemini API key (or set GEMINI_API_KEY)")
    p.add_argument("--model", default="gemini-3.5-flash-lite")
    p.add_argument("--input", action="append", required=True, dest="inputs", help="path to a normalized.json or docling native.json (repeatable)")
    p.add_argument("--source", action="append", required=True, dest="sources", help="label for the matching --input, e.g. a municipality/year slug (repeatable, same order as --input)")
    p.add_argument("--out", help="write combined legacy output to this single JSON file")
    p.add_argument("--out-dir", default=str(REPO_ROOT / "docs" / "examples" / "level3-analysis" / "out"), help="write one JSON file per --source into this directory (default: docs/examples/level3-analysis/out)")
    return p.parse_args()


def main() -> None:
    import sys
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = parse_args()
    if not args.api_key and not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        print("No credentials found: pass --api-key or set GEMINI_API_KEY / GOOGLE_API_KEY, or set GOOGLE_CLOUD_PROJECT", file=sys.stderr)
        sys.exit(1)
    if len(args.inputs) != len(args.sources):
        print("--input and --source must be given the same number of times", file=sys.stderr)
        sys.exit(1)

    codebook = load_codebook()
    codebook_listing = as_prompt_listing(codebook)
    codebook_by_code = by_code(codebook)

    combined_legacy: list[dict] = []
    for source, input_path in zip(args.sources, args.inputs):
        print(f"=== {source} ({input_path}) ===")
        try:
            legacy_records, production_output = process_one(
                source=source,
                input_path=Path(input_path),
                codebook_listing=codebook_listing,
                codebook_by_code=codebook_by_code,
                api_key=args.api_key,
                model=args.model,
            )
        except Exception as exc:  # noqa: BLE001 - one bad source must not kill the batch
            print(f"  FAILED: {exc!r}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            continue
            
        print(f"  -> {len(legacy_records)} legacy records, {len(production_output['line_items']) if production_output else 0} line items")
        combined_legacy.extend(legacy_records)

        if args.out_dir and legacy_records:
            out_dir = Path(args.out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            
            # Write both formats to the output directory for reference/comparison
            (out_dir / f"{source}_legacy.json").write_text(
                json.dumps(legacy_records, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if production_output:
                (out_dir / f"{source}_line_items.json").write_text(
                    json.dumps(production_output, ensure_ascii=False, indent=2), encoding="utf-8"
                )

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(combined_legacy, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWritten {len(combined_legacy)} total legacy records to {args.out}")


if __name__ == "__main__":
    main()
