"""
scripts/spike_category_mapping.py

Stage-3 validation spike (mirrors scripts/spike_docling.py's role for
stage 2): proves out the "common format across municipalities" approach --
unit normalization + LLM-assisted category classification against the
Ministry of Interior codebook -- against real docling output, before
committing to a full stage-3 design.

Input: one or more docling native.json files (DoclingDocument.export_to_dict()
export). This deliberately does NOT depend on origin/docling-example-outputs
being merged -- pull example files out of that branch yourself (e.g. via
`git show origin/docling-example-outputs:docs/examples/docling/<name>/native.json
> some/local/path.json`) and pass the local path in; that branch is expected
to keep changing independently of this script.

The Gemini API key is a required CLI argument (or set GEMINI_API_KEY and
omit --api-key) -- it is never read from a committed file, so a personal
key never ends up in git history.

Usage:
    python scripts/spike_category_mapping.py --api-key YOUR_KEY \\
        --input path/to/even_yehuda_native.json --source even_yehuda_2025 \\
        --out out/even_yehuda_2025.json

    # multiple inputs in one run:
    python scripts/spike_category_mapping.py \\
        --input a.json --source muni_a --input b.json --source muni_b \\
        --out-dir out/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.analysis.build_output import build_records, records_to_dicts
from pipeline.analysis.codebook import as_prompt_listing, by_code, load_codebook
from pipeline.analysis.docling_rows import extract_all_tables
from pipeline.analysis.llm_classify import classify_table


def process_one(source: str, input_path: Path, codebook_listing: str, codebook_by_code: dict, api_key: str, model: str) -> list[dict]:
    doc = json.loads(input_path.read_text(encoding="utf-8"))
    
    # Load scoped.json if present
    scoped_path = input_path.parent / "scoped.json"
    scope_data = None
    if scoped_path.is_file():
        try:
            scope_data = json.loads(scoped_path.read_text(encoding="utf-8"))
            print(f"  Loaded scope filtering metadata from: {scoped_path.name}")
        except Exception as exc:
            print(f"  Warning: failed to load scoped.json: {exc!r}")

    all_records: list[dict] = []

    for table in extract_all_tables(doc):
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
        result = classify_table(
            codebook_listing=codebook_listing,
            rows=rows_for_prompt,
            unit_known=unit_known,
            api_key=api_key,
            model=model,
        )
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
        all_records.extend(records_to_dicts(records))

    return all_records


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api-key", default=os.environ.get("GEMINI_API_KEY"), help="Gemini API key (or set GEMINI_API_KEY)")
    p.add_argument("--model", default="gemini-3.5-flash-lite")
    p.add_argument("--input", action="append", required=True, dest="inputs", help="path to a docling native.json (repeatable)")
    p.add_argument("--source", action="append", required=True, dest="sources", help="label for the matching --input, e.g. a municipality/year slug (repeatable, same order as --input)")
    p.add_argument("--out", help="write combined output to this single JSON file")
    p.add_argument("--out-dir", help="write one JSON file per --source into this directory")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.api_key:
        print("No API key: pass --api-key or set GEMINI_API_KEY", file=sys.stderr)
        sys.exit(1)
    if len(args.inputs) != len(args.sources):
        print("--input and --source must be given the same number of times", file=sys.stderr)
        sys.exit(1)

    codebook = load_codebook()
    codebook_listing = as_prompt_listing(codebook)
    codebook_by_code = by_code(codebook)

    combined: list[dict] = []
    for source, input_path in zip(args.sources, args.inputs):
        print(f"=== {source} ({input_path}) ===")
        try:
            records = process_one(
                source=source,
                input_path=Path(input_path),
                codebook_listing=codebook_listing,
                codebook_by_code=codebook_by_code,
                api_key=args.api_key,
                model=args.model,
            )
        except Exception as exc:  # noqa: BLE001 - one bad source must not kill the batch
            print(f"  FAILED: {exc!r}", file=sys.stderr)
            continue
        print(f"  -> {len(records)} output records")
        combined.extend(records)

        if args.out_dir:
            out_dir = Path(args.out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{source}.json").write_text(
                json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWritten {len(combined)} total records to {args.out}")


if __name__ == "__main__":
    main()
