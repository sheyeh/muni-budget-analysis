"""
scripts/summarize_categories.py

Reads every *.json file produced by spike_category_mapping.py /
run_category_mapping_dir.py out of a directory (default: out/) and sums
amount_ils per category. Defaults to "subtotal" rows only (see
pipeline/analysis/summarize.py's docstring for why: a subtotal already IS
the sum of its own line items, so including both would double-count).

Usage:
    python scripts/summarize_categories.py
    python scripts/summarize_categories.py --out-dir out --csv out/summary.csv
    python scripts/summarize_categories.py --row-types subtotal line_item
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.analysis.summarize import DEFAULT_ROW_TYPES, summarize_by_category


def load_records(out_dir: Path) -> list[dict]:
    records = []
    for path in sorted(out_dir.glob("*.json")):
        records.extend(json.loads(path.read_text(encoding="utf-8")))
    return records


def print_table(totals) -> None:
    if not totals:
        print("No matching rows found.")
        return
    for t in totals:
        flag = "  [unit unresolved!]" if t.unresolved_unit else ""
        label = t.label or "(unmatched)"
        print(f"{t.source:20s} {t.code or '-':6s} {label:25s} {t.amount_label:30s} {t.total_ils:>15,.0f}  (n={t.row_count}){flag}")


def write_csv(totals, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "code", "label", "amount_label", "total_ils", "row_count", "unresolved_unit"])
        for t in totals:
            writer.writerow([t.source, t.code or "", t.label or "", t.amount_label, t.total_ils, t.row_count, t.unresolved_unit])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out-dir", default="out", help="directory of spike_category_mapping.py output files (default: out)")
    p.add_argument("--row-types", nargs="+", default=list(DEFAULT_ROW_TYPES), help=f"which row_type(s) to include (default: {list(DEFAULT_ROW_TYPES)})")
    p.add_argument("--csv", help="also write the summary to this CSV path")
    p.add_argument("--json", help="also write the summary to this JSON path")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    if not out_dir.is_dir():
        print(f"Not a directory: {out_dir}", file=sys.stderr)
        sys.exit(1)

    records = load_records(out_dir)
    if not records:
        print(f"No *.json files found in {out_dir}", file=sys.stderr)
        sys.exit(1)

    totals = summarize_by_category(records, row_types=tuple(args.row_types))
    print_table(totals)

    if args.csv:
        write_csv(totals, Path(args.csv))
        print(f"\nWritten CSV to {args.csv}")
    if args.json:
        Path(args.json).write_text(
            json.dumps([vars(t) for t in totals], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Written JSON to {args.json}")


if __name__ == "__main__":
    main()
