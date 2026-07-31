"""
src/muni_budget_analysis/analysis/codebook.py

Loader for the Ministry of Interior's chart of accounts (moi_budget_codes.json).
"""

from __future__ import annotations

import json
from pathlib import Path

# Resolve path robustly, fallback to root repo location if not in packaged folder
_local_json = Path(__file__).resolve().parent / "moi_budget_codes.json"
if _local_json.exists():
    DEFAULT_PATH = _local_json
else:
    DEFAULT_PATH = Path(__file__).resolve().parents[3] / "pipeline" / "analysis" / "moi_budget_codes.json"


def load_codebook(path: Path = DEFAULT_PATH) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Ministry of Interior budget codes not found at: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def as_prompt_listing(entries: list[dict]) -> str:
    """One "code<TAB>label" line per entry, sorted by code -- the candidate
    list an LLM classification prompt matches row labels against."""
    return "\n".join(f"{e['code']}\t{e['label']}" for e in sorted(entries, key=lambda e: e["code"]))


def by_code(entries: list[dict]) -> dict[str, dict]:
    return {e["code"]: e for e in entries}
