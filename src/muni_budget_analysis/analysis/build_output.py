"""
src/muni_budget_analysis/analysis/build_output.py

Combine a table's extracted rows + LLM classification + resolved unit into
the spike's common-format output records.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from muni_budget_analysis.analysis.docling_rows import TableExtract
from muni_budget_analysis.analysis.llm_classify import ClassificationResult
from muni_budget_analysis.analysis.resolver import resolve_amount_type, resolve_fiscal_year
from muni_budget_analysis.analysis.codebook import load_codebook, by_code

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
    amount_type: str | None = None
    fiscal_year_value: int | None = None


def get_table_scope_filters(
    table: TableExtract,
    scope_data: dict | list | None,
) -> tuple[bool, dict[int, bool], dict[str | int, bool], dict | None]:
    """
    Extract Level 2.5 scope filters for a table from scoped.json data.

    Returns:
      (table_keep, rows_to_keep, cols_to_keep, table_scope)
    """
    rows_to_keep = {}
    cols_to_keep = {}
    table_keep = True

    table_scope = None
    if scope_data:
        if isinstance(scope_data, dict):
            # Try mock format (table index as key)
            table_scope = scope_data.get(str(table.table_index)) or scope_data.get(table.table_index)
            if not table_scope:
                # Try real scoped.json format (table_scopes list)
                scopes = scope_data.get("table_scopes", [])
                target_id = f"table-{table.table_index}"
                for s in scopes:
                    if s.get("table_id") == target_id or s.get("table_id") == getattr(table, "table_id", None):
                        table_scope = s
                        break
        elif isinstance(scope_data, list) and table.table_index < len(scope_data):
            table_scope = scope_data[table.table_index]

        if table_scope:
            if table_scope.get("year_axis") == "none":
                table_keep = bool(table_scope.get("keep", True))

            for r in table_scope.get("rows", []):
                rows_to_keep[r["index"]] = bool(r.get("keep", True))

            for c in table_scope.get("columns", []):
                cols_to_keep[c.get("header")] = bool(c.get("keep", True))
                cols_to_keep[c.get("index")] = bool(c.get("keep", True))

    return table_keep, rows_to_keep, cols_to_keep, table_scope


def build_records(
    *,
    source: str,
    table: TableExtract,
    classification: ClassificationResult,
    codebook_by_code: dict[str, dict],
    scope_data: dict | list | None = None,
    doc_fallback_multiplier: int | None = None,
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
    elif doc_fallback_multiplier is not None:
        unit_status, multiplier = "inferred_heuristic", doc_fallback_multiplier

    # Get document-level nominal fiscal target year
    target_year = 2025
    if isinstance(scope_data, dict) and "target_year" in scope_data:
        target_year = scope_data["target_year"]

    # 2. Respect Stage 2.5 Filters
    table_keep, rows_to_keep, cols_to_keep, table_scope = get_table_scope_filters(table, scope_data)

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

            # Resolve amount_type and fiscal_year_value
            resolved_amount_type = resolve_amount_type(amount_label or "", raw_value or "")
            
            resolved_year = None
            if table_scope and table_scope.get("year_axis") == "column":
                for col_scope in table_scope.get("columns", []):
                    if col_scope.get("index") == col_idx or col_scope.get("header") == amount_label:
                        resolved_year = col_scope.get("detected_year")
                        break
            
            if resolved_year is None:
                resolved_year = resolve_fiscal_year(amount_label or "", target_year)

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
                    amount_type=resolved_amount_type,
                    fiscal_year_value=resolved_year,
                )
            )
    return records


def build_line_items_json(
    muni_id: int,
    target_year: int,
    unit: str,
    records: list[OutputRecord],
    warnings: list[str],
    codebook_by_code: dict[str, dict] | None = None,
) -> dict:
    if codebook_by_code is None:
        try:
            codebook_by_code = by_code(load_codebook())
        except Exception:
            codebook_by_code = {}

    line_items = []
    current_category_fallback = "expense"
    
    for r in records:
        lbl = (r.source_label or "").strip()
        if lbl in ["הכנסות", "הכנסה", "סה\"כ הכנסות"]:
            current_category_fallback = "income"
        elif lbl in ["הוצאות", "הוצאה", "סה\"כ הוצאות"]:
            current_category_fallback = "expense"

        category = None
        if r.matched_code and codebook_by_code and r.matched_code in codebook_by_code:
            side = codebook_by_code[r.matched_code].get("side")
            if side == "receipts":
                category = "income"
            elif side == "payments":
                category = "expense"
        
        if not category:
            category = current_category_fallback
            
        if r.row_type == "divider":
            continue

        amount_val = None if r.is_percentage else r.amount_ils

        line_items.append({
            "classification_code": r.matched_code,
            "row_type": r.row_type,
            "raw_label_he": r.source_label,
            "category": category,
            "fiscal_year_value": r.fiscal_year_value,
            "amount_type": r.amount_type,
            "amount": amount_val,
        })
        
    return {
        "muni_id": muni_id,
        "fiscal_year": target_year,
        "unit": unit,
        "line_items": line_items,
        "warnings": warnings,
    }


def records_to_dicts(records: list[OutputRecord]) -> list[dict]:
    return [asdict(r) for r in records]
