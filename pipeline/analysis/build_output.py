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


def is_percentage_value(raw_val: str | None, header: str | None) -> bool:
    if raw_val is None:
        return False
    raw_val = raw_val.strip()
    if "%" in raw_val:
        return True
    if header:
        h_lower = header.lower()
        if any(keyword in h_lower for keyword in ["%", "אחוז", "שיעור"]):
            return True
    return False


def parse_percentage_val(raw_val: str) -> float | None:
    try:
        val = raw_val.strip().replace("%", "").replace(",", "")
        return float(val)
    except ValueError:
        return None


@dataclass
class OutputRecord:
    source: str
    table_index: int
    row_index: int
    source_label: str
    matched_code: str | None
    matched_label: str | None
    row_type: str  # "line_item" | "subtotal" | "grand_total" | "divider" | "unresolved"
    confidence: float
    note: str
    amount_label: str
    raw_value: str
    amount_ils: float | None
    unit_status: str  # "explicit" | "inferred" | "unresolved"
    unit_multiplier: int | None
    unusable_input: bool = False
    is_percentage: bool = False
    parsed_percentage: float | None = None
    validation_warning: str | None = None


def build_records(
    *,
    source: str,
    table: TableExtract,
    classification: ClassificationResult,
    codebook_by_code: dict[str, dict],
    scope_data: dict | list | None = None,
) -> list[OutputRecord]:
    # 1. Flexible Multipliers
    multiplier = None
    unit_status = "unresolved"

    if table.unit_explicit:
        if table.unit == "thousands":
            unit_status, multiplier = "explicit", 1000
        elif table.unit == "full":
            unit_status, multiplier = "explicit", 1
        else:
            unit_status, multiplier = "explicit", 1000
    elif classification.inferred_unit == "thousands":
        unit_status, multiplier = "inferred", 1000
    elif classification.inferred_unit == "full":
        unit_status, multiplier = "inferred", 1

    # 2. Respect Stage 2.5 Filters
    rows_to_keep = {}
    cols_to_keep = {}
    table_keep = True

    if scope_data:
        table_scope = None
        if isinstance(scope_data, dict):
            table_scope = scope_data.get(str(table.table_index)) or scope_data.get(table.table_index)
        elif isinstance(scope_data, list) and table.table_index < len(scope_data):
            table_scope = scope_data[table.table_index]
        
        if table_scope:
            if table_scope.get("year_axis") == "none":
                table_keep = bool(table_scope.get("keep", True))
            
            for r in table_scope.get("rows", []):
                rows_to_keep[r["index"]] = bool(r.get("keep", True))
            
            for c in table_scope.get("columns", []):
                cols_to_keep[c["header"]] = bool(c.get("keep", True))
                cols_to_keep[c["index"]] = bool(c.get("keep", True))

    if not table_keep:
        return []

    by_row_index = {c.row_index: c for c in classification.rows}
    records: list[OutputRecord] = []
    
    for row in table.rows:
        if row.row_index in rows_to_keep and not rows_to_keep[row.row_index]:
            continue

        cls = by_row_index.get(row.row_index)
        code = cls.code if cls else None
        
        # 3. Validation Warnings
        warning = None
        row_type = "divider"
        unusable_input = False
        
        if row.values:
            if not cls:
                warning = "LLM omitted row classification"
                row_type = "unresolved"
            else:
                row_type = cls.row_type
                unusable_input = cls.unusable_input
        
        if code:
            if code not in codebook_by_code:
                warning = f"Hallucinated code {code!r} not found in MoI codebook"
                matched_label = None
            else:
                matched_label = codebook_by_code[code].get("label")
        else:
            matched_label = None

        for col_idx, (amount_label, raw_value) in enumerate(row.values.items() or [(None, None)]):
            if amount_label in cols_to_keep and not cols_to_keep[amount_label]:
                continue
            if col_idx in cols_to_keep and not cols_to_keep[col_idx]:
                continue

            # 4. Rich Percentage Representation
            is_pct = is_percentage_value(raw_value, amount_label)
            parsed_pct = parse_percentage_val(raw_value) if (is_pct and raw_value is not None) else None
            
            if is_pct:
                amount_ils = None
            else:
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
                    row_type=row_type,
                    confidence=cls.confidence if cls else 0.0,
                    note=cls.note if cls else "structural row with no values (e.g. a bare section divider)",
                    amount_label=amount_label or "",
                    raw_value=raw_value or "",
                    amount_ils=amount_ils,
                    unit_status=unit_status,
                    unit_multiplier=multiplier,
                    unusable_input=unusable_input,
                    is_percentage=is_pct,
                    parsed_percentage=parsed_pct,
                    validation_warning=warning,
                )
            )
    return records


def records_to_dicts(records: list[OutputRecord]) -> list[dict]:
    return [asdict(r) for r in records]

