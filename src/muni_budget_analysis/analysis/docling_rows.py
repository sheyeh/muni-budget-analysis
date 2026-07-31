"""
src/muni_budget_analysis/analysis/docling_rows.py

Extract flat (label, {header: value}) rows and detect the amount unit from a
docling native.json export (DoclingDocument.export_to_dict()).

Contains definitions for TableRow and TableExtract which are also used by the
production Level 2/2.5 normalized.json reader.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NUMERIC_LIKE_RE = re.compile(r"[\d,.%-]")
UNIT_KEYWORD = "אלפי"  # "thousands of" (as in "באלפי ש\"ח")


@dataclass
class TableRow:
    row_index: int
    label: str
    values: dict[str, str]


@dataclass
class TableExtract:
    table_index: int
    header_texts: list[str]
    rows: list[TableRow]
    unit: str  # "thousands" | "unknown"
    unit_explicit: bool
    unit_evidence: str | None


def _rows_by_index(cells: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for c in cells:
        grouped.setdefault(c["start_row_offset_idx"], []).append(c)
    return grouped


def _is_numeric_like(text: str) -> bool:
    text = text.strip()
    if not text or text == "-":
        return True
    letters = sum(1 for ch in text if ch.isalpha())
    return letters == 0 and bool(NUMERIC_LIKE_RE.search(text))


def _pick_label_column(rows_by_idx: dict[int, list[dict]], header_row_indices: set[int], num_cols: int) -> int:
    numeric_hits = {col: 0 for col in range(num_cols)}
    total_hits = {col: 0 for col in range(num_cols)}
    for row_idx, cells in rows_by_idx.items():
        if row_idx in header_row_indices:
            continue
        for c in cells:
            col = c["start_col_offset_idx"]
            total_hits[col] += 1
            if _is_numeric_like(c["text"]):
                numeric_hits[col] += 1
    ratios = {
        col: (numeric_hits[col] / total_hits[col]) if total_hits[col] else 1.0
        for col in range(num_cols)
    }
    return min(ratios, key=ratios.get)


def _detect_unit(all_cells: list[dict], doc_texts: list[str]) -> tuple[str, bool, str | None]:
    for c in all_cells:
        if UNIT_KEYWORD in c["text"]:
            return "thousands", True, c["text"]
    for t in doc_texts:
        if UNIT_KEYWORD in t:
            return "thousands", True, t
    return "unknown", False, None


def extract_table(doc: dict, table_index: int) -> TableExtract:
    table = doc["tables"][table_index]
    cells = table["data"]["table_cells"]
    num_cols = table["data"]["num_cols"]
    rows_by_idx = _rows_by_index(cells)

    header_row_indices = {
        idx for idx, row_cells in rows_by_idx.items()
        if row_cells and all(c["column_header"] for c in row_cells)
    }
    if 0 in rows_by_idx:
        header_row_indices.add(0)
    header_cells = [c for idx in header_row_indices for c in rows_by_idx[idx]]
    header_by_col = {c["start_col_offset_idx"]: c["text"] for c in header_cells}

    label_col = _pick_label_column(rows_by_idx, header_row_indices, num_cols)

    doc_texts = [t.get("text", "") for t in doc.get("texts", [])]
    unit, unit_explicit, unit_evidence = _detect_unit(cells, doc_texts)

    rows: list[TableRow] = []
    for row_idx in sorted(rows_by_idx):
        if row_idx in header_row_indices:
            continue
        row_cells = sorted(rows_by_idx[row_idx], key=lambda c: c["start_col_offset_idx"])
        label = next((c["text"] for c in row_cells if c["start_col_offset_idx"] == label_col), "").strip()
        if not label:
            continue
        values = {
            header_by_col.get(c["start_col_offset_idx"], f"col{c['start_col_offset_idx']}"): c["text"]
            for c in row_cells
            if c["start_col_offset_idx"] != label_col
        }
        rows.append(TableRow(row_index=row_idx, label=label, values=values))

    return TableExtract(
        table_index=table_index,
        header_texts=[header_by_col[c] for c in sorted(header_by_col) if c != label_col],
        rows=rows,
        unit=unit,
        unit_explicit=unit_explicit,
        unit_evidence=unit_evidence,
    )


def extract_all_tables(doc: dict) -> list[TableExtract]:
    return [extract_table(doc, i) for i in range(len(doc.get("tables", [])))]
