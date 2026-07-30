"""
scripts/run_category_mapping_dir.py

Batch wrapper around scripts/spike_category_mapping.py: given a source
directory, discovers one docling native.json per municipality and runs the
mapping spike over all of them in one go, writing out/<name>.json per
municipality (matching name).

Discovery rules (checked in order, first one that finds anything wins):
  1. Each immediate subdirectory of --source-dir that contains a
     native.json (or --pattern) -> one source per subdirectory, named
     after the subdirectory (matches docs/examples/docling/<name>/native.json).
  2. Otherwise, each *.json file directly inside --source-dir -> one
     source per file, named after the file stem.

Usage:
    python scripts/run_category_mapping_dir.py --api-key YOUR_KEY \\
        --source-dir docs/examples/docling --out-dir out
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPIKE_SCRIPT = REPO_ROOT / "scripts" / "spike_category_mapping.py"


def discover_sources(source_dir: Path, pattern: str) -> list[tuple[str, Path]]:
    sources = []
    for child in sorted(source_dir.iterdir()):
        if child.is_dir() and (child / pattern).is_file():
            sources.append((child.name, child / pattern))
    if sources:
        return sources
    return [(p.stem, p) for p in sorted(source_dir.glob("*.json"))]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source-dir", required=True, help="directory to scan for docling native.json files")
    p.add_argument("--out-dir", required=True, help="directory to write one <name>.json per source into")
    p.add_argument("--pattern", default="native.json", help="filename to look for inside each subdirectory (default: native.json)")
    p.add_argument("--api-key", help="Gemini API key (or set GEMINI_API_KEY and omit this)")
    p.add_argument("--model", default="gemini-3.5-flash-lite")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    source_dir = Path(args.source_dir)
    if not source_dir.is_dir():
        print(f"Not a directory: {source_dir}", file=sys.stderr)
        sys.exit(1)

    sources = discover_sources(source_dir, args.pattern)
    if not sources:
        print(f"No sources found under {source_dir} (looked for */{args.pattern} and *.json)", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(sources)} source(s): {', '.join(name for name, _ in sources)}")

    cmd = [sys.executable, str(SPIKE_SCRIPT), "--model", args.model, "--out-dir", args.out_dir]
    if args.api_key:
        cmd += ["--api-key", args.api_key]
    for name, path in sources:
        cmd += ["--input", str(path), "--source", name]

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
