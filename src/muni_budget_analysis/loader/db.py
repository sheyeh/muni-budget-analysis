"""
db.py

Postgres I/O layer for the budget/budget_line_item loader: connects via
psycopg, upserts a budget row per (muni_id, fiscal_year), and wholesale-
replaces that budget's line items on every run (idempotent, no
versioning -- docs/handshake-level3-postgres.md).

One transaction per budget (not per batch): a bad manifest must not roll
back an otherwise-successful run, same resilience philosophy as
src/muni_budget_analysis/processing/run.py's process_one().
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from . import sync

logger = logging.getLogger(__name__)

UPSERT_BUDGET_SQL = """
    INSERT INTO budget (muni_id, fiscal_year, status, unit, source_ref, processed_at)
    VALUES (%(muni_id)s, %(fiscal_year)s, %(status)s, %(unit)s, %(source_ref)s, %(processed_at)s)
    ON CONFLICT (muni_id, fiscal_year) DO UPDATE SET
        status = excluded.status,
        unit = excluded.unit,
        source_ref = excluded.source_ref,
        processed_at = excluded.processed_at
    RETURNING id
"""

DELETE_LINE_ITEMS_SQL = "DELETE FROM budget_line_item WHERE budget_id = %s"

INSERT_LINE_ITEM_SQL = """
    INSERT INTO budget_line_item
        (budget_id, muni_id, classification_code, row_type, raw_label_he,
         category, fiscal_year_value, amount_type, amount)
    VALUES
        (%(budget_id)s, %(muni_id)s, %(classification_code)s, %(row_type)s, %(raw_label_he)s,
         %(category)s, %(fiscal_year_value)s, %(amount_type)s, %(amount)s)
"""


def connect(database_url: str):
    import psycopg

    return psycopg.connect(database_url)


def upsert_budget(cur, row: Dict[str, Any]) -> int:
    cur.execute(UPSERT_BUDGET_SQL, row)
    return cur.fetchone()[0]


def replace_line_items(cur, budget_id: int, muni_id: int, rows: List[Dict[str, Any]]) -> None:
    cur.execute(DELETE_LINE_ITEMS_SQL, (budget_id,))
    if not rows:
        return
    params = [
        {"budget_id": budget_id, "muni_id": muni_id, **row}
        for row in rows
    ]
    cur.executemany(INSERT_LINE_ITEM_SQL, params)


def sync_one(conn, manifest_path: Path, processed_dir: Path, analysis_dir: Path) -> Dict[str, Any]:
    """Load one manifest.json (under processed_dir) + its line_items.json
    (under the parallel analysis_dir tree, per
    docs/handshake-level3-postgres.md) + sibling scoped.json, upsert
    budget + wholesale-replace its line items in one transaction. Never
    raises -- returns a summary dict, including on failure.
    """
    manifest_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    muni_id = manifest["muni_id"]

    try:
        analysis_doc_dir = sync.resolve_analysis_dir(manifest_path, processed_dir, analysis_dir)
        line_items_doc = sync.load_line_items(analysis_doc_dir)
        fiscal_year = sync.resolve_fiscal_year(manifest_dir, line_items_doc)

        if fiscal_year is None:
            logger.warning(
                "muni_id=%s: no fiscal_year available (no line_items.json or "
                "scoped.json), skipping", muni_id,
            )
            return {"muni_id": muni_id, "status": "skipped", "reason": "no_fiscal_year"}

        source_ref = str(manifest_path)
        budget_row = sync.build_budget_row(manifest, line_items_doc, fiscal_year, source_ref)
        line_item_rows = (
            sync.build_line_item_rows(line_items_doc) if line_items_doc is not None else []
        )

        with conn.transaction():
            with conn.cursor() as cur:
                budget_id = upsert_budget(cur, budget_row)
                replace_line_items(cur, budget_id, muni_id, line_item_rows)

        logger.info(
            "muni_id=%s fiscal_year=%s status=%s line_items=%d",
            muni_id, fiscal_year, budget_row["status"], len(line_item_rows),
        )
        return {
            "muni_id": muni_id,
            "fiscal_year": fiscal_year,
            "status": budget_row["status"],
            "line_items": len(line_item_rows),
        }

    except Exception as exc:
        logger.exception("muni_id=%s: sync failed", muni_id)
        return {"muni_id": muni_id, "status": "error", "reason": str(exc)}


def sync_all(
    database_url: str, processed_dir: Path, analysis_dir: Path | None = None
) -> List[Dict[str, Any]]:
    """Sync every discovered budget under processed_dir. A single budget's
    failure never aborts the batch (mirrors run.py's run_batch()).

    analysis_dir defaults to processed_dir.parent / "analysis", matching
    analysis/run.py's own default when it isn't given --analysis-dir.
    """
    if analysis_dir is None:
        analysis_dir = processed_dir.parent / "analysis"

    manifest_paths = sync.discover_budgets(processed_dir)
    logger.info("Found %d manifest(s) under %s", len(manifest_paths), processed_dir)

    with connect(database_url) as conn:
        return [sync_one(conn, path, processed_dir, analysis_dir) for path in manifest_paths]
