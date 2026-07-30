"""
scripts/run_scope_classify.py

Level 2.5 batch runner: reads real normalized.json files produced by the
level-2 pipeline (src/muni_budget_analysis/processing/run.py) and produces
scoped.json alongside each one, per docs/adr/0003-llm-scope-classification-level-2-5.md.

This is still POC-shaped (per ADR-0003's "before full implementation" gate --
no production classifier module/tests exist yet), but unlike
scripts/spike_scope_classify.py (hand-transcribed table snippets) this reads
real docling/excel output through normalize.py's actual normalized.json
shape, closing the gap ADR-0003 flagged as unverified ("normalize.py's
actual column-header strings for a table like this are unknown until level
2's Task 7 lands").

Cost/quota bound: classifying every table in every document is not
attempted here -- tel_aviv_2026 alone has 353 tables, shafir_2026 has 200.
Each table is one live Gemini call; the Gemini Developer API free tier caps
at 20 requests/day/model (pipeline/analysis/README.md), and even on Vertex
AI (this script's backend, no daily cap) hundreds of calls per doc is not
"running the examples through the stage" so much as a full-corpus batch job
that hasn't been scoped/costed. Per document, only the first
--max-tables-per-doc (default 5) tables that have at least one header row
and 2+ columns are classified -- enough to exercise the stage end-to-end
per sample document without an uncontrolled bill. Raise the cap explicitly
for a real full-corpus run.

Usage:
    python scripts/run_scope_classify.py --processed-dir data/processed

Requires GOOGLE_CLOUD_PROJECT (+ application-default credentials) or
GEMINI_API_KEY, same as spike_scope_classify.py.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are classifying one table from a municipal budget document (Hebrew, RTL). \
You are told the section heading, the table's column headers, and the first cell of every row. \
You are NOT given the table's numeric data -- classify based on headers/row-labels only.

Task: determine which axis (columns or rows) carries a fiscal year, and which specific \
columns/rows belong to the given target fiscal year.

Respond with strict JSON, no prose, matching this shape:
{
  "year_axis": "column" | "row" | "none",
  "columns": [ {"index": int, "header": string, "detected_year": int | null, "keep": bool}, ... ]
    // present only if year_axis == "column", one entry per header in order given
  "rows": [ {"index": int, "row_label": string, "detected_year": int | null, "keep": bool}, ... ]
    // present only if year_axis == "row", one entry per row_label in order given
  "keep": bool,       // present only if year_axis == "none" -- whole table, always false
  "reason": string | null,   // required if year_axis == "none", optional elsewhere
  "confidence": float  // 0-1, your confidence in this table's classification as a whole
}

Rules for "keep":
- true if detected_year equals the target fiscal year.
- true if the column/row is structural (a category name, code, or label column with no year of \
its own) -- it's needed to interpret whichever year IS kept, regardless of year.
- false for every other year's column/row.
- If year_axis == "none" (no year signal anywhere in headers or row labels), the whole table is \
unusable for fiscal-year-specific extraction: keep = false, and say why in "reason".
"""

MODEL_NAME = "gemini-2.5-flash"
SCOPED_FILENAME = "scoped.json"
YEAR_RE = re.compile(r"(20\d{2})")


def extract_year(source_filename: str) -> Optional[int]:
    match = YEAR_RE.search(source_filename)
    return int(match.group(1)) if match else None


def table_headers_and_first_column(table: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Pull header row(s) + first-cell-of-every-row out of a normalized.json
    table's flat `rows` (list of row -> list of {"text", "is_header", ...}
    cells). Returns None for tables too small to classify meaningfully
    (no header row, or <2 columns).
    """
    rows = table["rows"]
    if not rows:
        return None

    header_rows = [r for r in rows if r and all(c.get("is_header") for c in r)]
    data_rows = [r for r in rows if r not in header_rows]
    if not header_rows or table.get("num_cols", 0) < 2:
        return None

    headers = [c["text"] for c in header_rows[0]]
    first_column_values = [row[0]["text"] for row in data_rows if row]
    if not first_column_values:
        return None
    return {"headers": headers, "first_column_values": first_column_values}


def section_title_for(normalized: Dict[str, Any], section_id: Optional[str]) -> str:
    for sec in normalized["sections"]:
        if sec["section_id"] == section_id:
            return sec["title"]
    return ""


def select_tables_to_classify(normalized: Dict[str, Any], max_tables: int) -> List[Dict[str, Any]]:
    candidates = []
    for table in normalized["tables"]:
        payload = table_headers_and_first_column(table)
        if payload is None:
            continue
        candidates.append({
            "table_id": table["table_id"],
            "section_title": section_title_for(normalized, table.get("section_id")),
            **payload,
        })
    return candidates[:max_tables]


def classify_table(sample: Dict[str, Any], target_year: int) -> Dict[str, Any]:
    """Same isolated call as scripts/spike_scope_classify.py's classify_table()."""
    from google import genai
    from google.genai import types

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if project:
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        client = genai.Client(vertexai=True, project=project, location=location)
    elif api_key:
        client = genai.Client(api_key=api_key)
    else:
        raise RuntimeError(
            "Neither GOOGLE_CLOUD_PROJECT (Vertex AI) nor GEMINI_API_KEY/"
            "GOOGLE_API_KEY (Gemini Developer API) is set."
        )

    request = {
        "section_title": sample["section_title"],
        "target_year": target_year,
        "headers": sample["headers"],
        "first_column_values": sample["first_column_values"],
    }
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=json.dumps(request, ensure_ascii=False),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.0,
        ),
    )
    return json.loads(response.text)


def process_document(doc_dir: Path, max_tables: int) -> Optional[Dict[str, Any]]:
    normalized_path = doc_dir / "normalized.json"
    if not normalized_path.exists():
        return None
    with open(normalized_path, "r", encoding="utf-8") as f:
        normalized = json.load(f)

    target_year = extract_year(normalized["source_filename"])
    if target_year is None:
        logger.warning("No fiscal year detected in %s, skipping", normalized["source_filename"])
        return None

    candidates = select_tables_to_classify(normalized, max_tables)
    logger.info(
        "%s: %d/%d tables classifiable, classifying %d (target_year=%d)",
        normalized["source_filename"], len(candidates), len(normalized["tables"]),
        len(candidates), target_year,
    )

    table_scopes = []
    for sample in candidates:
        try:
            result = classify_table(sample, target_year)
        except Exception as exc:  # a single table's failure must not lose the rest, or crash the batch
            logger.warning("  [%s] classification failed: %s", sample["table_id"], exc)
            continue
        table_scopes.append({
            "table_id": sample["table_id"],
            "section_title": sample["section_title"],
            **result,
        })
        logger.info(
            "  [%s] year_axis=%s confidence=%s",
            sample["table_id"], result.get("year_axis"), result.get("confidence"),
        )
        time.sleep(1)  # light client-side pacing, avoid tripping per-minute rate limits

    scoped = {
        "muni_id": normalized["muni_id"],
        "source_filename": normalized["source_filename"],
        "target_year": target_year,
        "tables_total": len(normalized["tables"]),
        "tables_classified": len(table_scopes),
        "table_scopes": table_scopes,
    }
    scoped_path = doc_dir / SCOPED_FILENAME
    with open(scoped_path, "w", encoding="utf-8") as f:
        json.dump(scoped, f, ensure_ascii=False, indent=2)
    logger.info("Wrote %s", scoped_path)
    return scoped


def main() -> int:
    parser = argparse.ArgumentParser(description="Run level-2.5 scope classification over level-2 output")
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"))
    parser.add_argument(
        "--max-tables-per-doc", type=int, default=5,
        help="Cap on live classifier calls per document (cost/quota guard, see module docstring)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    doc_dirs = sorted(
        p for p in args.processed_dir.glob("*/*") if (p / "normalized.json").exists()
    )
    logger.info("Found %d processed document(s) under %s", len(doc_dirs), args.processed_dir)

    processed = 0
    for doc_dir in doc_dirs:
        result = process_document(doc_dir, args.max_tables_per_doc)
        if result is not None:
            processed += 1

    print(f"\n=== Level-2.5 Scope Classification Complete ===")
    print(f"Documents processed: {processed}/{len(doc_dirs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
