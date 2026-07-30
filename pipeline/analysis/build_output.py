"""
Combine a table's extracted rows + LLM classification + resolved unit into
the spike's common-format output records (one record per row per amount
column -- a "long" format, since different documents have different
numbers of amount columns e.g. one document has 8 fiscal-year/type columns
per row, another has just 1).

Known limitation (not solved by this spike): not every non-label column is
a currency amount -- e.g. even_yehuda_2025 has a percentage-utilization
column and a footnote-reference-number column mixed in with real amount
columns, and there's no reliable per-column semantic classification here
yet. `parse_amount` only turns comma-formatted numbers into amount_ils;
anything else (percentages, stray small footnote-ref integers) is left as
raw_value with amount_ils=None, except plain small integers which still
parse as (probably-bogus) amounts -- a visible, low-severity artifact to
fix when fiscal-year/amount-type column resolution is tackled directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from pipeline.analysis.docling_rows import TableExtract
from pipeline.analysis.llm_classify import ClassificationResult

AMOUNT_RE = re.compile(r"^-?[\d,]+(\.\d+)?$")


def parse_amount(raw: str) -> float | None:
    raw = raw.strip()
    if not raw or raw == "-":
        return 0.0
    if not AMOUNT_RE.match(raw):
        return None
    return float(raw.replace(",", ""))


@dataclass
class OutputRecord:
    source: str
    table_index: int
    row_index: int
    source_label: str
    matched_code: str | None
    matched_label: str | None
    row_type: str  # "line_item" | "subtotal" | "grand_total" | "divider"
    confidence: float
    note: str
    amount_label: str
    raw_value: str
    amount_ils: float | None
    unit_status: str  # "explicit" | "inferred" | "unresolved"
    unit_multiplier: int | None


def build_records(
    *,
    source: str,
    table: TableExtract,
    classification: ClassificationResult,
    codebook_by_code: dict[str, dict],
) -> list[OutputRecord]:
    if table.unit_explicit:
        unit_status, multiplier = "explicit", 1000
    elif classification.inferred_unit == "thousands":
        unit_status, multiplier = "inferred", 1000
    elif classification.inferred_unit == "full":
        unit_status, multiplier = "inferred", 1
    else:
        unit_status, multiplier = "unresolved", None

    by_row_index = {c.row_index: c for c in classification.rows}
    records: list[OutputRecord] = []
    for row in table.rows:
        cls = by_row_index.get(row.row_index)
        code = cls.code if cls else None
        matched_label = codebook_by_code.get(code, {}).get("label") if code else None
        for amount_label, raw_value in (row.values.items() or [(None, None)]):
            amount = parse_amount(raw_value) if raw_value is not None else None
            amount_ils = amount * multiplier if (amount is not None and multiplier is not None) else None
            records.append(
                OutputRecord(
                    source=source,
                    table_index=table.table_index,
                    row_index=row.row_index,
                    source_label=row.label,
                    matched_code=code,
                    matched_label=matched_label,
                    row_type=cls.row_type if cls else "divider",
                    confidence=cls.confidence if cls else 0.0,
                    note=cls.note if cls else "structural row with no values (e.g. a bare section divider)",
                    amount_label=amount_label or "",
                    raw_value=raw_value or "",
                    amount_ils=amount_ils,
                    unit_status=unit_status,
                    unit_multiplier=multiplier,
                )
            )
    return records


def records_to_dicts(records: list[OutputRecord]) -> list[dict]:
    return [asdict(r) for r in records]
