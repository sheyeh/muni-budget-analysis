"""
pipeline/analysis/resolver.py

Heuristic resolvers to map Hebrew table headers/metadata to structured properties,
such as amount_type enums and fiscal year values.
"""

from __future__ import annotations

import re


def resolve_amount_type(header: str, raw_value: str) -> str:
    """Resolve amount_type enum based on column header and raw value content.

    Possible enums:
    - budgeted
    - actual_current_prices
    - actual_adjusted_prices
    - execution_pct
    - change
    """
    h = header.lower()
    raw_value_str = str(raw_value or "").strip()
    
    # 1. Percentage / Execution rate columns
    if "%" in raw_value_str or any(kw in h for kw in ["%", "אחוז", "שיעור"]):
        return "execution_pct"
        
    # 2. Change / Delta columns
    if any(kw in h for kw in ["שינוי", "הפרש", "גידול", "קיטון"]):
        return "change"
        
    # 3. Budgeted columns
    if any(kw in h for kw in ["תקציב", "מסגרת תקציב", "הצעה", "מאושר"]):
        return "budgeted"
        
    # 4. Actual execution columns (distinguishing current vs adjusted prices)
    if any(kw in h for kw in ["ביצוע", "למעשה", "שוטפים", "שוטף"]):
        if any(kw in h for kw in ["מקודם", "מתואם", "ריאלי", "קבועים", "למחירי"]):
            return "actual_adjusted_prices"
        return "actual_current_prices"
        
    # Default fallback
    return "budgeted"


def resolve_fiscal_year(header: str, target_year: int) -> int:
    """Parse 4-digit fiscal year from header text, or fallback to the nominal budget year."""
    match = re.search(r"\b(20\d{2})\b", header)
    if match:
        return int(match.group(1))
    return target_year
