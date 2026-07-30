"""
scripts/spike_scope_classify.py

POC/gate spike for the level 2.5 scope-filtering stage (see
docs/adr/0003-llm-scope-classification-level-2-5.md and CONTEXT.md's
"Year axis / keep" glossary entry). Per prd.md's "Task 0: Validation spike"
pattern -- this gates full implementation. Deliverable: this script's real
output, sent to the level 3 dev team for contract sign-off before the
classifier module / batch runner / tests are built.

normalized.json doesn't exist as a real generated file yet (level 2's
Task 7 batch run isn't landed on worktree-level2-pipeline), so the table
snippets below are hand-transcribed from the real docling markdown output
already checked into the repo -- NOT synthetic/made-up data:
  - even_yehuda_2025: docs/examples/docling/even_yehuda_2025/document.md
  - jerusalem_2026 (two tables): .claude/worktrees/level2-pipeline/docs/
    examples/docling/jerusalem_2026/document.md, lines 611-643 (debt
    breakdown, column-axis but no 2026) and 624-643 (15-year forecast,
    row-axis) and 351-375 (staffing table, nested/grouped 2025+2026
    headers -- a harder real-world case, included to stress-test the
    classifier against docling's imperfect grouped-header parsing).

Each sample is what the classifier would actually receive per table:
column headers + first-cell-of-every-row (never full row data), plus
section_title and target_year for context. See ADR-0003 for why: row
data doesn't change which columns/rows belong to which year, and leaving
it out keeps the payload small and the hallucination surface low.

Usage:
    python scripts/spike_scope_classify.py

Requires either:
  - GOOGLE_CLOUD_PROJECT (Vertex AI project with Gemini access) +
    application-default credentials (`gcloud auth application-default
    login`) or a service account -- the production backend per ADR-0003, or
  - GEMINI_API_KEY / GOOGLE_API_KEY (Gemini Developer API key, from
    https://aistudio.google.com/apikey) -- no GCP project needed, fine
    for this spike, note in findings if this path was used instead.

Writes output to scripts/spike_output/scope_classify/
per sample: <name>.request.json (what was sent) and <name>.response.json
(the model's raw output). If credentials/package aren't available, this
prints a clear error and exits non-zero -- it does NOT fabricate a
stand-in response, since the whole point of this spike is producing real
model output for the level 3 team to review.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

OUTPUT_DIR = Path(__file__).parent / "spike_output" / "scope_classify"

MODEL_NAME = "gemini-2.0-flash-001"

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


def build_request(
    section_title: str,
    headers: List[str],
    first_column_values: List[str],
    target_year: int,
) -> Dict[str, Any]:
    return {
        "section_title": section_title,
        "target_year": target_year,
        "headers": headers,
        "first_column_values": first_column_values,
    }


# --- Hand-transcribed real samples (see module docstring for provenance) ---

SAMPLES: Dict[str, Dict[str, Any]] = {
    "even_yehuda_2025_main_table": build_request(
        section_title="תקציב רגיל לשנת 2025",
        target_year=2025,
        headers=[
            "הסעיף התקציבי",
            "ביצוע 2023 מחירים שוטפים",
            "מסגרת תקציב לשנת 2024",
            "ביצוע 2024 מחירים שוטפים",
            "מקדמים בשימוש הרשות",
            "ביצוע 2024 מקודם למחירי 2025",
            "שינויים כולל התייעלות",
            "פירוט מס' הסבר לשינויים",
            "מסגרת תקציב לשנת 2025",
        ],
        first_column_values=[
            "הכנסות",
            "ארנונה כללית )מיסים(",
            "מפעל המים",
            "עצמיות חינוך",
            "עצמיות רווחה",
            "עצמיות אחר",
            "סה\"כ הכנסות עצמיות",
            "תקבולים משרד החינוך",
            "הוצאות",
            "שכר כללי",
        ],
    ),
    "jerusalem_2026_debt_breakdown_no_target_year": build_request(
        section_title="התפלגות חובות העירייה למוסדות פיננסיים וניתוח השוואתי של השינויים לתקופה מיום 31.12.24 ועד ליום 31.12.25",
        target_year=2026,
        headers=[
            "שם הבנק",
            "יתרת קרן ליום נומינלית 31/12/24",
            "יתרת קרן ליום משוערכת 31/12/24",
            "הלוואות גיוס לשנת 2025",
            "יתרת קרן ליום נומינלית 31/12/25",
            "יתרת קרן ליום משוערכת 31/12/25",
            "שיעור גידול 12/2024-12/2025",
            "התפלגות התחייבויות לבנקים",
            "התפלגות מצטברת",
        ],
        first_column_values=[
            "בנק לאומי סינדיקציה",
            "בנק לאומי",
            "דיסקונט",
            "הפועלים",
            "המזרחי",
            "בינלאומי",
            "מרכנתיל דיסקונט בע\"מ",
            "סה\"כ",
        ],
    ),
    "jerusalem_2026_debt_forecast_row_axis": build_request(
        section_title="תחזית פירעון מלוות העירייה לשנים 2040-2026",
        target_year=2026,
        headers=[
            "שנה",
            "החזר קרן",
            "החזר ריבית",
            "הפרשי הצמדה",
            "סה\"כ",
            "שיעור ההחזר מסך כל ההחזרים השנתי",
            "שיעור ההחזר המצטבר",
        ],
        first_column_values=[
            "2026", "2027", "2028", "2029", "2030", "2031", "2032",
            "2033", "2034", "2035", "2036", "2037", "2038", "2039", "2040",
        ],
    ),
    "jerusalem_2026_staffing_nested_headers": build_request(
        section_title="התפלגות תקנים לפי מקור מימון",
        target_year=2026,
        headers=[
            "מינהל / אגף",
            "שיא כוח אדם בתקנים 2025",
            "תקציב 2025 - במימון תקנים עירוני",
            "תקציב 2025 - תקנים ייעודיים",
            "שיא כוח אדם בתקנים 2026",
            "תקציב 2026 - במימון תקנים עירוני",
            "תקציב 2026 - תקנים ייעודיים",
        ],
        first_column_values=[
            "מינהל כללי",
            "יחידות מטה מועצת שונות",
            "אגף יחידות סמך מזכירות העיר",
            "האגף למדיניות ותכנון אסטרטגי",
            "אגף דוברות והסברה",
        ],
    ),
}


def classify_table(sample: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calls Vertex AI Gemini with the given table sample. Isolated behind
    this one function (per ADR-0003 -- same isolation pattern as
    ADR-0001's docling carve-out) so a later heuristic pre-filter or a
    different backend can wrap/replace this without touching callers or
    the output shape.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        raise RuntimeError(
            "google-genai not installed. `pip install google-genai` "
            "(not yet in requirements.txt -- this is a spike, add it "
            "there once the classifier module is built for real)."
        ) from e

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if project:
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        client = genai.Client(vertexai=True, project=project, location=location)
    elif api_key:
        # Gemini Developer API fallback -- same model/prompt/output shape,
        # no GCP project/ADC setup required. Fine for this spike (real
        # implementation targets Vertex AI per ADR-0003, for consistency
        # with the rest of this repo's GCP usage); note which backend
        # actually produced the output when reporting findings.
        client = genai.Client(api_key=api_key)
    else:
        raise RuntimeError(
            "Neither GOOGLE_CLOUD_PROJECT (Vertex AI, needs "
            "`gcloud auth application-default login`) nor "
            "GEMINI_API_KEY/GOOGLE_API_KEY (Gemini Developer API, just "
            "an API key from https://aistudio.google.com/apikey) is set. "
            "Need one to run this spike live."
        )
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=json.dumps(sample, ensure_ascii=False),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.0,
        ),
    )
    return json.loads(response.text)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    failures = 0
    for name, sample in SAMPLES.items():
        request_path = OUTPUT_DIR / f"{name}.request.json"
        with open(request_path, "w", encoding="utf-8") as f:
            json.dump(sample, f, ensure_ascii=False, indent=2)

        print(f"[{name}] wrote request -> {request_path}")
        try:
            result = classify_table(sample)
        except RuntimeError as e:
            print(f"[{name}] SKIPPED (no live call): {e}", file=sys.stderr)
            failures += 1
            continue

        response_path = OUTPUT_DIR / f"{name}.response.json"
        with open(response_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[{name}] wrote response -> {response_path}")
        print(f"[{name}] year_axis={result.get('year_axis')} confidence={result.get('confidence')}")

    if failures == len(SAMPLES):
        print(
            "\nNo live classification ran for any sample -- see the "
            "RuntimeError(s) above. This spike needs a real GCP project "
            "with Vertex AI Gemini access (GOOGLE_CLOUD_PROJECT env var, "
            "`gcloud auth application-default login`) plus `pip install "
            "google-genai` before it can produce the level-3-team "
            "deliverable this stage is gated on.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
