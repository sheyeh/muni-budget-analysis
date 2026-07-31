"""
src/muni_budget_analysis/analysis/normalized_input.py

Extracts structured TableExtract objects from Level 2's normalized.json format.
"""

from __future__ import annotations

import re
from muni_budget_analysis.analysis.docling_rows import TableExtract, TableRow

NUMERIC_LIKE_RE = re.compile(r"[\d,.%-]")
UNIT_KEYWORD = "אלפי"  # "thousands of" (as in "באלפי ש\"ח")


def _is_numeric_like(text: str) -> bool:
    text = text.strip()
    if not text or text == "-":
        return True
    letters = sum(1 for ch in text if ch.isalpha())
    return letters == 0 and bool(NUMERIC_LIKE_RE.search(text))


def _pick_label_column(rows: list[list[dict]], header_row_indices: set[int], num_cols: int) -> int:
    if num_cols <= 0:
        return 0
    numeric_hits = {col: 0 for col in range(num_cols)}
    total_hits = {col: 0 for col in range(num_cols)}
    for row_idx, row_cells in enumerate(rows):
        if row_idx in header_row_indices:
            continue
        for col, cell in enumerate(row_cells):
            if col >= num_cols:
                break
            text = cell.get("text", "")
            total_hits[col] += 1
            if _is_numeric_like(text):
                numeric_hits[col] += 1
    ratios = {
        col: (numeric_hits[col] / total_hits[col]) if total_hits[col] else 1.0
        for col in range(num_cols)
    }
    if not ratios:
        return 0
    return min(ratios, key=ratios.get)


def _detect_unit(rows: list[list[dict]], section_titles: list[str]) -> tuple[str, bool, str | None]:
    for row_cells in rows:
        for cell in row_cells:
            text = cell.get("text", "")
            if UNIT_KEYWORD in text:
                return "thousands", True, text
    for title in section_titles:
        if UNIT_KEYWORD in title:
            return "thousands", True, title
    return "unknown", False, None


def extract_normalized_table(
    table: dict,
    table_index: int,
    section_titles: list[str],
) -> TableExtract:
    rows_data = table.get("rows", [])
    num_cols = table.get("num_cols", 0)
    table_id = table.get("table_id", f"table-{table_index}")

    # Determine header rows: row 0 or rows where all cells are is_header
    header_row_indices = set()
    for row_idx, row_cells in enumerate(rows_data):
        if row_cells and (row_idx == 0 or all(c.get("is_header", False) for c in row_cells)):
            header_row_indices.add(row_idx)

    header_cells = [c for idx in header_row_indices for c in rows_data[idx]]
    
    # Map column index to header text
    header_by_col = {}
    for row_idx in sorted(header_row_indices):
        for col_idx, cell in enumerate(rows_data[row_idx]):
            text = cell.get("text", "").strip()
            if text:
                header_by_col[col_idx] = text

    # Fill in missing header names with column indices if empty
    for c in range(num_cols):
        if c not in header_by_col:
            header_by_col[c] = f"col{c}"

    label_col = _pick_label_column(rows_data, header_row_indices, num_cols)

    # Unit detection
    unit, unit_explicit, unit_evidence = _detect_unit(rows_data, section_titles)

    rows: list[TableRow] = []
    for row_idx, row_cells in enumerate(rows_data):
        if row_idx in header_row_indices:
            continue
        
        # Extract label
        label = ""
        if label_col < len(row_cells):
            label = row_cells[label_col].get("text", "").strip()
        if not label:
            continue

        # Extract other column values
        values = {}
        for col_idx, cell in enumerate(row_cells):
            if col_idx == label_col:
                continue
            header_text = header_by_col.get(col_idx, f"col{col_idx}")
            values[header_text] = cell.get("text", "")

        rows.append(TableRow(row_index=row_idx, label=label, values=values))

    # Keep a reference of header texts excluding the label column
    header_texts = [header_by_col[c] for c in sorted(header_by_col) if c != label_col]

    return TableExtract(
        table_index=table_index,
        header_texts=header_texts,
        rows=rows,
        unit=unit,
        unit_explicit=unit_explicit,
        unit_evidence=unit_evidence,
    )


def extract_all_normalized_tables(normalized_doc: dict) -> list[TableExtract]:
    section_titles = [s.get("title", "") for s in normalized_doc.get("sections", [])]
    tables = []
    for idx, table in enumerate(normalized_doc.get("tables", [])):
        tables.append(extract_normalized_table(table, idx, section_titles))
    return tables
