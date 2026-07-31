"""
sync.py

Pure, DB-agnostic logic for syncing stage-2 manifest.json + stage-3
line_items.json into the budget/budget_line_item schema
(docs/handshake-level3-postgres.md). No I/O beyond reading the JSON files
themselves -- building rows and connecting to Postgres are separate
concerns (see db.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

MANIFEST_FILENAME = "manifest.json"
LINE_ITEMS_FILENAME = "line_items.json"
SCOPED_FILENAME = "scoped.json"


def discover_budgets(processed_dir: Path) -> List[Path]:
    """Find every manifest.json under processed_dir/{muni_id}/{output_key}/."""
    return sorted(processed_dir.glob(f"*/*/{MANIFEST_FILENAME}"))


def load_line_items(manifest_dir: Path) -> Optional[Dict[str, Any]]:
    """Read manifest_dir/line_items.json, or None if absent."""
    path = manifest_dir / LINE_ITEMS_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_scoped(manifest_dir: Path) -> Optional[Dict[str, Any]]:
    """Read manifest_dir/scoped.json, or None if absent."""
    path = manifest_dir / SCOPED_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def derive_status(manifest: Dict[str, Any], line_items_doc: Optional[Dict[str, Any]]) -> str:
    """Determine budget.status from manifest.json + (optional) line_items.json.

    line_items.json present: processed_partial if its warnings are non-empty,
    else processed_success -- same warnings-non-empty-means-partial
    convention level 2 already uses for its own manifest.

    line_items.json absent: manifest.status == "failed" means level 2 itself
    failed, nothing to load -> processed_failed. manifest.status in
    (success, partial) means level 2 succeeded but stage 3 hasn't produced
    output yet for this budget -> pending (not "attempted and failed").
    """
    if line_items_doc is not None:
        return "processed_partial" if line_items_doc.get("warnings") else "processed_success"

    if manifest.get("status") == "failed":
        return "processed_failed"
    return "pending"


def resolve_fiscal_year(
    manifest_dir: Path, line_items_doc: Optional[Dict[str, Any]]
) -> Optional[int]:
    """Determine budget.fiscal_year: from line_items.json when present, else
    fall back to sibling scoped.json's target_year. None if neither exists.
    """
    if line_items_doc is not None:
        return line_items_doc["fiscal_year"]

    scoped = load_scoped(manifest_dir)
    if scoped is not None:
        return scoped["target_year"]

    return None


def build_budget_row(
    manifest: Dict[str, Any],
    line_items_doc: Optional[Dict[str, Any]],
    fiscal_year: int,
    source_ref: str,
) -> Dict[str, Any]:
    """Build a budget row dict: {muni_id, fiscal_year, status, unit,
    source_ref, processed_at}.
    """
    return {
        "muni_id": manifest["muni_id"],
        "fiscal_year": fiscal_year,
        "status": derive_status(manifest, line_items_doc),
        "unit": line_items_doc["unit"] if line_items_doc is not None else None,
        "source_ref": source_ref,
        "processed_at": manifest["processed_at"],
    }


def build_line_item_rows(line_items_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Map line_items.json's line_items entries 1:1 to budget_line_item row
    dicts. No filtering -- build_output.py already guarantees no `divider`
    rows reach line_items.json.
    """
    return [
        {
            "classification_code": item["classification_code"],
            "row_type": item["row_type"],
            "raw_label_he": item["raw_label_he"],
            "category": item["category"],
            "fiscal_year_value": item["fiscal_year_value"],
            "amount_type": item["amount_type"],
            "amount": item["amount"],
        }
        for item in line_items_doc["line_items"]
    ]
