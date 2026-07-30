"""
Loader for pipeline/analysis/data/moi_budget_codes.json (produced by
scripts/parse_codebook.py from ספר-קידודים-ברשויות-מקומיות.pdf, the
Ministry of Interior's chart of accounts).
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "moi_budget_codes.json"


def load_codebook(path: Path = DEFAULT_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def as_prompt_listing(entries: list[dict]) -> str:
    """One "code<TAB>label" line per entry, sorted by code -- the candidate
    list an LLM classification prompt matches row labels against."""
    return "\n".join(f"{e['code']}\t{e['label']}" for e in sorted(entries, key=lambda e: e["code"]))


def by_code(entries: list[dict]) -> dict[str, dict]:
    return {e["code"]: e for e in entries}
