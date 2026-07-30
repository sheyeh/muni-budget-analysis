"""
Gemini-based classification of budget-table row labels against the MoI
codebook, plus unit inference when a table has no explicit unit marker.

The API key is always a caller-supplied argument (CLI flag or env var read
by the caller) -- never hardcoded or read from a committed file, so a
personal key never ends up in git history.

This module's only public entry point (`classify_table`) takes a plain
prompt-building/response-parsing shape; the actual model call is isolated
in `_call_gemini` so a different provider could be swapped in behind the
same signature later without touching the prompt/parsing logic.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional, List
from pydantic import BaseModel, Field

# Default to cost-effective gemini-3.5-flash-lite as aligned
DEFAULT_MODEL = "gemini-3.5-flash-lite"

MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0  # doubles each retry: 2s, 4s, 8s

PROMPT_TEMPLATE = """\
You are classifying line items from an Israeli local authority (municipal) \
budget document against the official Ministry of Interior chart of \
accounts ("ספר קידודים"). Row labels may be noisy: OCR errors, or Hebrew \
words in reversed order (e.g. "המים מפעל" instead of "מפעל המים"). Use your \
knowledge of Israeli municipal budgeting to read through such noise.

Candidate codes (tab-separated "code<TAB>label", one per line):
{codebook_listing}

{unit_instructions}

Table rows to classify (tab-separated "row_index<TAB>label<TAB>sample values"):
{rows_listing}

Every row is one of:
- "line_item": a specific budget line (e.g. "ארנונה כללית", "שכר עובדי \
חינוך"). Give it the most specific ("deepest") matching code.
- "subtotal": a "סה\"כ ..." (total/sum) row that names ONE category or \
chapter (e.g. "סה\"כ חינוך" = Total Education, "סה\"כ הוצאות כלליות" = \
Total General Expenses). This STILL gets that category's code (a broader \
chapter/section-level code is fine and expected here) -- do not null it \
out just because it is a total; it names a real category, it's just an \
aggregate of that category's line items rather than a line item itself.
- "grand_total": an aggregate that spans multiple unrelated categories or \
isn't a category at all (e.g. "סה\"כ הכנסות", "סה\"כ תקציב", "עודף/גרעון", \
a bare section-divider label like "הכנסות"/"הוצאות"). These get "code": \
null since no single code applies.

Rules for "unusable_input":
- Set "unusable_input": true if the label is severely garbled, contains \
mostly random symbols/punctuation (e.g. "###$$$"), is pure OCR noise with \
no discernible financial/budgetary meaning (e.g. "עצמיות ANN"), or has been \
so badly mangled by extraction that it cannot be classified.
- Otherwise, default "unusable_input": false.
"""

UNIT_INSTRUCTIONS_KNOWN = "The document states its amounts are in {unit}; do not re-derive this."
UNIT_INSTRUCTIONS_UNKNOWN = """\
This table has NO explicit unit marker (no "אלפי" / "thousands" label \
found anywhere in it). Based on the row labels and the magnitude of the \
values, plus your general knowledge of Israeli municipal budget scales, \
infer whether these amounts are already in full NIS or in thousands of NIS.\
"""


@dataclass
class RowClassification:
    row_index: int
    code: Optional[str]
    row_type: str  # "line_item" | "subtotal" | "grand_total"
    confidence: float
    note: str
    unusable_input: bool = False


@dataclass
class ClassificationResult:
    rows: list[RowClassification]
    inferred_unit: Optional[str] = None
    inferred_unit_confidence: Optional[float] = None
    inferred_unit_rationale: Optional[str] = None


# Pydantic models for Google GenAI Structured Outputs
class RowInference(BaseModel):
    row_index: int = Field(description="The row index of the table being classified.")
    code: Optional[str] = Field(None, description="The matched MoI chart of accounts code (e.g. '111', '6111'), or null if no single specific code applies.")
    row_type: str = Field(description="One of: 'line_item', 'subtotal', or 'grand_total'.")
    confidence: float = Field(description="Confidence rating of the code classification between 0.0 and 1.0.")
    note: str = Field(description="Brief reason for the match/non-match.")
    unusable_input: bool = Field(False, description="Set to True if the input row label is severely malformed, completely garbled, or unusable due to parsing errors.")

class UnitInference(BaseModel):
    unit: str = Field(description="One of 'thousands' or 'full'.")
    confidence: float = Field(description="Confidence in unit inference from 0.0 to 1.0.")
    rationale: str = Field(description="Brief reasoning for the unit inference.")

class TableClassificationResponse(BaseModel):
    unit_inference: Optional[UnitInference] = Field(None, description="Unit inference if table has no explicit unit.")
    rows: List[RowInference] = Field(description="Classification entries for every table row.")


def _build_prompt(codebook_listing: str, rows: list[tuple[int, str, str]], unit_known: str | None) -> str:
    if unit_known:
        unit_instructions = UNIT_INSTRUCTIONS_KNOWN.format(unit=unit_known)
    else:
        unit_instructions = UNIT_INSTRUCTIONS_UNKNOWN
    rows_listing = "\n".join(f"{idx}\t{label}\t{sample}" for idx, label, sample in rows)
    return PROMPT_TEMPLATE.format(
        codebook_listing=codebook_listing,
        unit_instructions=unit_instructions,
        rows_listing=rows_listing,
    )


def _error_details(exc: Exception) -> list[dict]:
    try:
        return exc.details["error"]["details"]
    except (AttributeError, KeyError, TypeError):
        return []


def _is_daily_quota_exhausted(exc: Exception) -> bool:
    for detail in _error_details(exc):
        if not detail.get("@type", "").endswith("QuotaFailure"):
            continue
        for violation in detail.get("violations", []):
            haystack = f"{violation.get('quotaId', '')} {violation.get('quotaMetric', '')}"
            if "PerDay" in haystack or "per_day" in haystack.lower():
                return True
    return False


def _server_suggested_delay(exc: Exception) -> float | None:
    for detail in _error_details(exc):
        if detail.get("@type", "").endswith("RetryInfo"):
            raw = detail.get("retryDelay", "")
            try:
                return float(raw.rstrip("s"))
            except ValueError:
                return None
    return None


def _is_retryable(exc: Exception) -> bool:
    from google.genai import errors

    if isinstance(exc, errors.ServerError):
        return True  # 5xx: transient server-side failure
    if isinstance(exc, errors.ClientError):
        if getattr(exc, "code", None) != 429:
            return False
        return not _is_daily_quota_exhausted(exc)  # per-minute limit, not the daily cap
    return False


class QuotaExhaustedError(Exception):
    """Raised in place of the raw 429 when it's a per-day quota (won't clear on retry)."""


def _call_gemini(prompt: str, api_key: str | None, model: str) -> str:
    import os
    from google import genai
    from google.genai import types

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project:
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        client = genai.Client(vertexai=True, project=project, location=location)
    elif api_key:
        client = genai.Client(api_key=api_key)
    else:
        raise RuntimeError(
            "Neither GOOGLE_CLOUD_PROJECT (Vertex AI) nor GEMINI_API_KEY/GOOGLE_API_KEY "
            "(Gemini Developer API) is set."
        )
    delay = RETRY_BASE_DELAY_SECONDS
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=TableClassificationResponse,
                ),
            )
            return response.text
        except Exception as exc:
            if _is_daily_quota_exhausted(exc):
                raise QuotaExhaustedError(
                    f"Daily quota exhausted for model {model!r}. This is a per-day cap "
                    "(e.g. the free tier's ~20 requests/day/model) -- retrying now won't "
                    "help; wait for the quota to reset or use a different --model/API key/tier. "
                    f"Original error: {exc}"
                ) from exc
            if attempt == MAX_RETRIES or not _is_retryable(exc):
                raise
            wait = _server_suggested_delay(exc) or delay
            print(f"    Gemini call failed (attempt {attempt}/{MAX_RETRIES}): {exc!r} -- retrying in {wait:.0f}s")
            time.sleep(wait)
            delay *= 2


def _parse_response(raw: str) -> ClassificationResult:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    parsed = json.loads(text)

    rows = [
        RowClassification(
            row_index=item["row_index"],
            code=item.get("code"),
            row_type=item.get("row_type", "line_item"),
            confidence=float(item.get("confidence", 0.0)),
            note=item.get("note", ""),
            unusable_input=bool(item.get("unusable_input", False)),
        )
        for item in parsed["rows"]
    ]
    unit_inference = parsed.get("unit_inference")
    if unit_inference and unit_inference.get("unit"):
        return ClassificationResult(
            rows=rows,
            inferred_unit=unit_inference.get("unit"),
            inferred_unit_confidence=unit_inference.get("confidence"),
            inferred_unit_rationale=unit_inference.get("rationale"),
        )
    return ClassificationResult(rows=rows)


def classify_table(
    *,
    codebook_listing: str,
    rows: list[tuple[int, str, str]],
    unit_known: str | None,
    api_key: str | None,
    model: str = DEFAULT_MODEL,
) -> ClassificationResult:
    prompt = _build_prompt(codebook_listing, rows, unit_known)
    raw = _call_gemini(prompt, api_key=api_key, model=model)
    return _parse_response(raw)

