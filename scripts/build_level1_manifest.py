"""
scripts/build_level1_manifest.py

Level-1 manifest adapter: walks the real scraped budget corpus under data/
and emits data/level1_manifest.json, the [{muni_id, budget_filename, source}]
shape src/muni_budget_analysis/processing/run.py's load_level1_manifest() /
ingest.py's resolve_source() already expect -- see CONTEXT.md's "Level-1
manifest" entry.

Never trusts budget_files.csv/.json's downloaded_path column -- it records
data/budgets/{muni}/... but real files live one level shallower, at
data/{muni}/... (docs/data-directory.md). Files are discovered by walking
data/ directly instead. The CSV is only used to cross-reference optional
provenance fields (municipality_name/type/website_url) by (muni_id, year) --
never for path resolution.

Only year-folder files are emitted; general/ (no year signal anywhere) is
Task 2's problem, out of scope here -- see prd-level1-corpus-ingestion.md.

Usage:
    python scripts/build_level1_manifest.py
"""

import argparse
import csv
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

MUNI_DIR_RE = re.compile(r"^(\d+)_(.+)$")
DEFAULT_DATA_DIR = Path("data")
DEFAULT_BUDGET_FILES_CSV = Path("data/budget_files.csv")
DEFAULT_OUTPUT = Path("data/level1_manifest.json")


def parse_muni_dirname(dirname: str) -> Tuple[int, str]:
    """Split a data/ muni directory name '{muni_id}_{muni_name}' into (muni_id, muni_name)."""
    match = MUNI_DIR_RE.match(dirname)
    if match is None:
        raise ValueError(f"Directory name doesn't match '{{muni_id}}_{{muni_name}}': {dirname!r}")
    return int(match.group(1)), match.group(2)


def load_csv_index(csv_path: Path) -> Dict[Tuple[int, int], Dict[str, str]]:
    """
    Index budget_files.csv by (municipality_code, budget_year) for cross-referencing
    provenance (municipality_name/type/website_url) onto discovered manifest records.
    Never used to resolve file paths -- downloaded_path in this file is stale
    (records data/budgets/{muni}/... vs. the real data/{muni}/...).
    """
    index: Dict[Tuple[int, int], Dict[str, str]] = {}
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                code = int(row["municipality_code"])
                year = int(row["budget_year"])
            except (KeyError, ValueError):
                continue
            if year == 0:  # sentinel for "no year determined" -- can't match a real year folder
                continue
            index[(code, year)] = row
    return index


def discover_year_records(data_dir: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Walk data_dir/{muni_dir}/{year_dir}/{file} -- only all-digit year_dir names,
    which excludes 'general/' (no year signal, Task 2's problem) for free.

    A year folder holding more than one real file was expected never to
    happen (prd-level1-corpus-ingestion.md Task 1's verified assumption),
    but the real corpus violates it for Tel Aviv-Yafo (muni_id=5000, every
    year 2009-2026) and Holon (muni_id=6600, 5 years) -- companion documents
    (full budget vs. summary, or a multi-part PDF) per year, not scraper
    noise. Which file is "the" budget for those slots is a real product
    decision, not this script's to guess -- see
    https://github.com/sheyeh/muni-budget-analysis/issues/33. Such slots are
    logged and excluded from the returned records rather than raising, so
    the rest of the corpus still produces a manifest.

    Returns (records, skipped) where skipped describes each excluded
    multi-file slot for the caller's summary.
    """
    records = []
    skipped = []
    for muni_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        muni_id, muni_name = parse_muni_dirname(muni_dir.name)
        for year_dir in sorted(p for p in muni_dir.iterdir() if p.is_dir() and p.name.isdigit()):
            year = int(year_dir.name)
            files = sorted(
                p for p in year_dir.iterdir() if p.is_file() and p.name != ".DS_Store"
            )
            if len(files) > 1:
                logger.warning(
                    "Skipping %s: %d candidate files (needs manual resolution, "
                    "see issue #33): %s",
                    year_dir, len(files), [p.name for p in files],
                )
                skipped.append({
                    "muni_id": muni_id,
                    "year": year,
                    "file_names": [p.name for p in files],
                })
                continue
            if not files:
                continue
            records.append({
                "muni_id": muni_id,
                "muni_dir_name": muni_dir.name,
                "year": year,
                "file_path": files[0],
            })
    return records, skipped


def build_manifest_record(
    muni_id: int,
    muni_dir_name: str,
    year: int,
    file_path: Path,
    repo_root: Path,
    csv_index: Dict[Tuple[int, int], Dict[str, str]],
) -> Dict[str, Any]:
    """
    Build one level-1 manifest record.

    budget_filename is synthesized as "{muni_dir_name}_{year}{ext}" rather than
    reusing the real source-site filename (a bare timestamp, e.g.
    "1541058045.2762.pdf", carrying no year). Level 2.5's extract_year()
    (scripts/run_scope_classify.py) parses the target fiscal year out of this
    field via a `20\\d{2}` regex -- unchanged by this script -- so the year
    must be encoded here for that downstream contract to keep working. This is
    a deliberate workaround, not the real source filename; see
    docs/adr/0005-synthesized-budget-filename-for-year-extraction.md.

    For year < 2000, no synthesized filename can satisfy extract_year()'s
    `20\\d{2}` regex -- that's a limit of the regex itself, not something
    this synthesis can route around. The record is still emitted (level 2
    doesn't call extract_year() at all), but level 2.5 will skip it; see
    https://github.com/sheyeh/muni-budget-analysis/issues/34.
    """
    if year < 2000:
        logger.warning(
            "muni_id=%d year=%d: extract_year()'s `20\\d{2}` regex can't match "
            "pre-2000 years -- level 2.5 will skip this document until that "
            "regex is widened, see issue #34",
            muni_id, year,
        )
    budget_filename = f"{muni_dir_name}_{year}{file_path.suffix}"
    resolved_path = file_path.resolve()
    try:
        # The common case: data/ lives directly under repo_root, so a relative
        # path is emitted (ingest.py's resolve_source() joins it back with
        # PROJECT_ROOT). Falls back to an absolute path if the file resolves
        # outside repo_root (e.g. data/ reached via a symlink/junction to
        # elsewhere) -- resolve_source() uses absolute source values as-is.
        source_value = resolved_path.relative_to(repo_root).as_posix()
    except ValueError:
        source_value = str(resolved_path)

    record: Dict[str, Any] = {
        "muni_id": muni_id,
        "budget_filename": budget_filename,
        "source": {"kind": "local", "value": source_value},
    }

    csv_row = csv_index.get((muni_id, year))
    if csv_row is None:
        logger.warning(
            "No budget_files.csv match for muni_id=%d year=%d, skipping enrichment",
            muni_id, year,
        )
    else:
        record["municipality_name"] = csv_row.get("municipality_name")
        record["municipality_type"] = csv_row.get("municipality_type")
        record["website_url"] = csv_row.get("website_url")

    return record


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a level-1 manifest from the real data/ corpus"
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--budget-files-csv", type=Path, default=DEFAULT_BUDGET_FILES_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    repo_root = Path(__file__).resolve().parents[1]
    csv_index = load_csv_index(args.budget_files_csv)
    logger.info("Loaded %d (muni, year) row(s) from %s", len(csv_index), args.budget_files_csv)

    discovered, skipped = discover_year_records(args.data_dir)
    logger.info("Discovered %d year-folder file(s) under %s", len(discovered), args.data_dir)

    records = [
        build_manifest_record(
            d["muni_id"], d["muni_dir_name"], d["year"], d["file_path"], repo_root, csv_index
        )
        for d in discovered
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    munis_covered = len({r["muni_id"] for r in records})
    print("\n=== Level-1 Manifest Build Complete ===")
    print(f"Records written: {len(records)}")
    print(f"Munis covered: {munis_covered}")
    print(f"Output: {args.output}")
    if skipped:
        skipped_munis = sorted({s['muni_id'] for s in skipped})
        print(f"Year-slots skipped (multiple files, needs manual resolution): {len(skipped)}")
        print(f"  Affected muni_id(s): {skipped_munis}")
        print("  See https://github.com/sheyeh/muni-budget-analysis/issues/33")
    pre_2000_count = sum(1 for d in discovered if d["year"] < 2000)
    if pre_2000_count:
        print(f"Pre-2000 records included but unusable by level 2.5: {pre_2000_count}")
        print("  See https://github.com/sheyeh/muni-budget-analysis/issues/34")
    return 0


if __name__ == "__main__":
    sys.exit(main())
