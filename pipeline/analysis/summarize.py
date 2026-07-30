"""
Summarize spike_category_mapping.py output records by category.

Defaults to only "subtotal" rows (not "line_item") because a subtotal row
IS the sum of its own line items -- summing both together for the same
category would double-count (see pipeline/analysis/README.md). Once
fiscal-year/amount-type parsing exists, this can be pointed at "line_item"
rows instead/as well with a from-scratch bottom-up sum; for now, trusting
each document's own subtotal rows is the safer default.

Grouping key includes `amount_label` (the raw column header, e.g. a
particular fiscal year/budget-vs-actual column) because different amount
columns represent different things -- summing "תקציב 2025" together with
"ביצוע 2023" for the same category would be meaningless. Grouping also
includes `source` (one municipality/document) rather than rolling
everything into one cross-municipality total, for the same reason.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

DEFAULT_ROW_TYPES = ("subtotal",)


@dataclass
class CategoryTotal:
    source: str
    code: str | None
    label: str | None
    amount_label: str
    total_ils: float
    row_count: int
    unresolved_unit: bool  # True if any contributing row had unit_status == "unresolved"


def summarize_by_category(
    records: list[dict], row_types: tuple[str, ...] = DEFAULT_ROW_TYPES
) -> list[CategoryTotal]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        if r.get("row_type") not in row_types:
            continue
        if r.get("amount_ils") is None:
            continue
        key = (r["source"], r.get("matched_code"), r.get("matched_label"), r.get("amount_label", ""))
        groups[key].append(r)

    totals = [
        CategoryTotal(
            source=key[0],
            code=key[1],
            label=key[2],
            amount_label=key[3],
            total_ils=sum(r["amount_ils"] for r in rows),
            row_count=len(rows),
            unresolved_unit=any(r.get("unit_status") == "unresolved" for r in rows),
        )
        for key, rows in groups.items()
    ]
    totals.sort(key=lambda t: (t.source, t.code or "", t.amount_label))
    return totals
