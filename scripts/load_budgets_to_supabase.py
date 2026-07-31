"""
scripts/load_budgets_to_supabase.py

CLI wrapper around muni_budget_analysis.loader: syncs every processed
budget's manifest.json + line_items.json into Postgres's budget /
budget_line_item tables (docs/handshake-level3-postgres.md, issue #13).

Usage:
    python scripts/load_budgets_to_supabase.py --processed-dir data/processed
    python scripts/load_budgets_to_supabase.py --database-url postgresql://...

Requires the muni / classification_code dimension tables to already be
seeded (see scripts/generate_dimension_seed.py) -- FK constraints will fail
loudly otherwise.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from muni_budget_analysis.loader.db import sync_all  # noqa: E402

DEFAULT_PROCESSED_DIR = REPO_ROOT / "data" / "processed"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR,
        help=f"directory to scan for {{muni_id}}/{{output_key}}/manifest.json (default: {DEFAULT_PROCESSED_DIR})",
    )
    p.add_argument(
        "--analysis-dir", type=Path, default=None,
        help="directory to read {muni_id}/{output_key}/line_items.json from "
        "(default: --processed-dir's sibling 'analysis' directory, matching "
        "analysis/run.py's own default)",
    )
    p.add_argument(
        "--database-url", default=os.environ.get("DATABASE_URL"),
        help="Postgres connection string (or set DATABASE_URL)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if not args.database_url:
        print("No database URL: pass --database-url or set DATABASE_URL", file=sys.stderr)
        sys.exit(1)
    if not args.processed_dir.is_dir():
        print(f"Not a directory: {args.processed_dir}", file=sys.stderr)
        sys.exit(1)

    results = sync_all(args.database_url, args.processed_dir, args.analysis_dir)

    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result["status"]] = status_counts.get(result["status"], 0) + 1

    print("\n=== Budget Sync Complete ===")
    print(f"Total manifests found: {len(results)}")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")


if __name__ == "__main__":
    main()
