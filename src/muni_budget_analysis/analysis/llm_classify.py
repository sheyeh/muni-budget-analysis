"""
src/muni_budget_analysis/analysis/llm_classify.py

Gemini-based classification of budget-table row labels against the MoI
codebook, plus unit inference when a table has no explicit unit marker.

Separates general classification instruction patterns (passed as system instructions)
from dynamic data payloads (passed as user content) to improve matching accuracy.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional, List, Any
from pydantic import BaseModel, Field

# Default to cost-effective gemini-3.5-flash-lite as aligned
DEFAULT_MODEL = "gemini-3.5-flash-lite"

MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0  # doubles each retry: 2s, 4s, 8s


SYSTEM_PROMPT = """You are an expert financial classifier specializing in Israeli municipal budgets.
Your task is to classify line items and totals from local authority budget tables against the official Ministry of Interior (MoI) standard chart of accounts ("ספר קידודים").

Rules for matching:
1. Classification Accuracy: Match each row label to the most appropriate, correct code from the Candidate Codes listing.
2. No Hallucinations: NEVER invent, hallucinate, or assume a code that is not present in the Candidate Codes listing. If no valid match exists, set "code": null.
3. Word-Order Reversal: Hebrew table row labels may be noisy, showing OCR errors or reversed word-order (e.g. "המים מפעל" instead of "מפעל המים", or "ארנונה מגורים" <-> "מגורים ארנונה", or "שכר מורים" <-> "מורים שכר"). Carefully read through such reversals to find the true semantic meaning.
4. Granularity Depth: Match the specificity of the item.
   - Specific, deep leaf line items (e.g., "שכר מורים", "רכישת ציוד משרדי") should be classified as "line_item" and map to the most specific matching child codes.
   - Broader aggregates/subtotals (e.g., "סה"כ חינוך יסודי" or "סה"כ הוצאות") must be classified as "subtotal" and mapped to the broader parent category or chapter code.
   - Spanning aggregates or general document dividers (e.g. "סה"כ תקציב", "סה"כ הוצאות כלליות", "גרעון/עודף", "הכנסות", "הוצאות") must be classified as "grand_total" and map to "code": null since no single code applies.

Rules for "unusable_input":
- Set "unusable_input": true if the label is severely garbled, contains mostly random symbols/punctuation (e.g. "###$$$"), is pure OCR noise with no discernible financial/budgetary meaning (e.g. "עצמיות ANN"), or has been so badly mangled by extraction that it cannot be classified. Otherwise, set "unusable_input": false.
"""

USER_PROMPT_TEMPLATE = """\
Please classify the following table rows against the Candidate Codes listing below.

{unit_instructions}

Candidate Codes (tab-separated "code<TAB>label"):
{codebook_listing}

Table Rows (tab-separated "row_index<TAB>label<TAB>sample values"):
{rows_listing}
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


def _build_user_prompt(codebook_listing: str, rows: list[tuple[int, str, str]], unit_known: str | None) -> str:
    if unit_known:
        unit_instructions = UNIT_INSTRUCTIONS_KNOWN.format(unit=unit_known)
    else:
        unit_instructions = UNIT_INSTRUCTIONS_UNKNOWN
    rows_listing = "\n".join(f"{idx}\t{label}\t{sample}" for idx, label, sample in rows)
    return USER_PROMPT_TEMPLATE.format(
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
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.0,
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
    prompt = _build_user_prompt(codebook_listing, rows, unit_known)
    raw = _call_gemini(prompt, api_key=api_key, model=model)
    return _parse_response(raw)


async def _call_gemini_async(prompt: str, api_key: str | None, model: str) -> str:
    import os
    import asyncio
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
            # We use client.aio for async API calls in the new google-genai SDK
            response = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.0,
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
            print(f"    Gemini async call failed (attempt {attempt}/{MAX_RETRIES}): {exc!r} -- retrying in {wait:.0f}s")
            await asyncio.sleep(wait)
            delay *= 2


async def classify_table_async(
    *,
    codebook_listing: str,
    rows: list[tuple[int, str, str]],
    unit_known: str | None,
    api_key: str | None,
    model: str = DEFAULT_MODEL,
) -> ClassificationResult:
    prompt = _build_user_prompt(codebook_listing, rows, unit_known)
    raw = await _call_gemini_async(prompt, api_key=api_key, model=model)
    return _parse_response(raw)


async def classify_tables_batch_async(
    batch_tasks: list[dict[str, Any]],
    api_key: str | None,
    model: str = DEFAULT_MODEL,
    max_concurrency: int = 5,
) -> list[tuple[int, ClassificationResult | Exception]]:
    """
    Classify multiple tables concurrently using asyncio and Semaphore.
    """
    import asyncio
    sem = asyncio.Semaphore(max_concurrency)

    async def worker(task: dict[str, Any]) -> tuple[int, ClassificationResult | Exception]:
        async with sem:
            try:
                result = await classify_table_async(
                    codebook_listing=task['codebook_listing'],
                    rows=task['rows'],
                    unit_known=task['unit_known'],
                    api_key=api_key,
                    model=model,
                )
                return task['table_index'], result
            except Exception as exc:
                return task['table_index'], exc

    tasks = [worker(task) for task in batch_tasks]
    return await asyncio.gather(*tasks)
