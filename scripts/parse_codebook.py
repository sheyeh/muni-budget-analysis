"""
scripts/parse_codebook.py

Parses ספר-קידודים-ברשויות-מקומיות.pdf (the Ministry of Interior's "Yellow
Book" chart of accounts for Israeli local authorities) into two structured,
machine-usable taxonomies: pipeline/analysis/moi_budget_codes.json (the main
hierarchical code tree) and pipeline/analysis/moi_budget_code_suffixes.json
(the orthogonal suffix-code catalog, see Scope below).

Why this needs custom parsing instead of plain pypdf/pdftotext:
  1. The PDF's font has a broken cmap: the Hebrew letter "נ" (nun) is mapped
     to the codepoint U+00F0 ('ð') in extracted text. Fix: replace 'ð' -> 'נ'
     before doing anything else.
  2. Each word's characters come out in visual (left-to-right) glyph order
     rather than logical Hebrew reading order. Fix: reverse the characters
     of every non-numeric word (numeric codes like "631" are already correct
     and must NOT be reversed).
  3. Pages 2-12 use a two-column layout: physically-left column = the
     תשלומים (payments/expense) side hierarchy (chapters 6-9), physically-
     right column = the תקבולים (receipts/income) side hierarchy (chapters
     1-5). A plain linear text extraction (pypdf) interleaves both columns
     per visual line, merging unrelated entries together. Fix: use
     pdfplumber's per-word bounding boxes to (a) group words into rows by
     `top`, (b) split each row into left/right zones at the widest x-gap,
     (c) sort each zone's words by x0 descending (RTL reading order) to
     reconstruct "<code> <label>" for that zone independently.

Scope: the main hierarchical code tree lives on pages 2-12 (0-indexed,
printed page numbers 2-12; parse_codebook()). Pages 13-15 ("סיומות סעיפי
תקבולים/תשלומים", parse_suffix_codebook()) are a separate, orthogonal 1-3
digit suffix-code catalog appended to a base code to form a 5-6 digit
account number -- e.g. "21" here means "אגרות מים וביוב" (a receipts
suffix), unrelated to main-tree code "21" ("תברואה"). Written to a
separate output file rather than merged into moi_budget_codes.json,
because suffix codes collide with main-tree code strings and reuse the
same 1-9 digits once per side (side is assigned per-page, not by leading
digit, since -- unlike the main tree -- each suffix page is single-side).

Side is inferred from the code's leading digit: '1'-'5' -> תקבולים
(income), '6'-'9' -> תשלומים (expense). This holds even for the
"תשלומים בלתי רגילים" (irregular payments) entries, which are nested as
section "99" under chapter 9 rather than being a true separate top-level
chapter -- confirmed by the code hierarchy (991, 9911, ...) following the
same digit-length-equals-depth rule as everything else.

Usage:
    python scripts/parse_codebook.py
    python scripts/parse_codebook.py --check 631,111,6111   # print specific codes and exit
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pdfplumber

REPO_ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = REPO_ROOT / "ספר-קידודים-ברשויות-מקומיות.pdf"
# NOTE: this constant previously said ".../data/moi_budget_codes.json", but the
# file actually loaded at runtime (pipeline/analysis/codebook.py's DEFAULT_PATH)
# has no "data/" subdirectory -- fixed here so a re-run writes where it's read from.
OUTPUT_PATH = REPO_ROOT / "pipeline" / "analysis" / "moi_budget_codes.json"
SUFFIX_OUTPUT_PATH = REPO_ROOT / "pipeline" / "analysis" / "moi_budget_code_suffixes.json"

MOJIBAKE_NUN = "ð"  # 'ð' stands in for Hebrew 'נ' in this PDF's font
FIRST_CONTENT_PAGE = 2   # printed page 2 (0-indexed page 2)
LAST_CONTENT_PAGE = 12   # printed page 12 (0-indexed page 12); 13-15 are suffix tables
# Suffix pages (see module docstring, item 3): a separate, orthogonal 1-3 digit
# code space appended to a base code to form a 5-6 digit account number. Unlike
# the main tree's pages, each suffix page is single-side -- side is determined
# by which page a row came from, not by the code's leading digit.
SUFFIX_PAGE_SIDES = {13: "receipts", 14: "payments", 15: "payments"}
FOOTER_TOP_CUTOFF = 780  # branding/page-number band, always below this
ROW_TOP_TOLERANCE = 2.0  # px tolerance for grouping words into the same row
ZONE_GAP_THRESHOLD = 40.0  # px gap that signals a left/right column split

# Page 11's "4 מפעלים / 9 מפעלים" chapter-title banner row uses much wider
# code<->label spacing than every other row in the document, so the
# gap-based zone splitter (correctly, for every other row) tears its single
# "<label> <code>" group into a label-only zone and a code-only zone, both
# of which get dropped (no digit token / no label). Rather than loosen
# ZONE_GAP_THRESHOLD for one outlier row and risk mis-splitting normal rows,
# patch the two resulting level-1 labels directly. "9" also collides with a
# same-named banner on page 12 for section 99 ("תשלומים בלתי רגילים",
# irregular payments) -- that page-12 label is section 99's real name, not
# chapter 9's; chapter 9's own name is "מפעלים" (enterprises), matching its
# income-side mirror chapter "4".
LEVEL1_LABEL_OVERRIDES = {
    "4": "מפעלים",
    "9": "מפעלים",
}

# Several suffix-page category banners wrap across 2-3 lines (same class of
# issue as LEVEL1_LABEL_OVERRIDES above, just more of them here): the digit
# token sits on one line while earlier line(s) of the title have no digit
# token at all, so parse_zone() -- correctly, for the normal one-line case --
# treats them as a labelless stray banner fragment and drops them. Verified
# against the source PDF's visual layout, not guessed.
SUFFIX_LABEL_OVERRIDES = {
    ("receipts", "8"): 'השתתפות בעלים ע"ח עבודות פתוח',
    ("payments", "1"): "משכורות ושכר עבודה לעובדים לפי תקן",
    ("payments", "2"): "משכורות ושכר עבודה לעובדים בלי תקן",
    ("payments", "4"): "אחזקת בנינים ואספקה וציוד",
    ("payments", "8"): "השתתפויות תמיכות ותרומות",
    ("payments", "81"): 'השתתפויות ותרומות למוסדות עפ"י חוק והסכמים',
    ("payments", "492"): "השתתפות בתקציב עזר (משרד הרשות ושרותים)",
}


def fix_word(text: str) -> str:
    fixed = text.replace(MOJIBAKE_NUN, "נ")
    if fixed.isdigit():
        return fixed
    return fixed[::-1]


def group_rows(words: list[dict]) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: w["top"]):
        if rows and abs(rows[-1][0]["top"] - w["top"]) <= ROW_TOP_TOLERANCE:
            rows[-1].append(w)
        else:
            rows.append([w])
    return rows


def split_zones(row: list[dict]) -> list[list[dict]]:
    row_sorted = sorted(row, key=lambda w: w["x0"])
    zones: list[list[dict]] = [[row_sorted[0]]]
    for prev, cur in zip(row_sorted, row_sorted[1:]):
        if cur["x0"] - prev["x1"] > ZONE_GAP_THRESHOLD:
            zones.append([])
        zones[-1].append(cur)
    return zones


def parse_zone(zone: list[dict]) -> list[dict]:
    """Split a zone's words (sorted RTL) into one or more code+label groups.

    A zone normally holds a single "<code> <label...>" group, but a handful
    of rows pack two groups into what looks like one zone (the visual gap
    between them is narrower than ZONE_GAP_THRESHOLD). Every digit token
    starts a new group, so this handles both cases without relying on the
    gap heuristic.
    """
    words = sorted(zone, key=lambda w: -w["x0"])
    texts = [fix_word(w["text"]) for w in words]

    groups: list[list[str]] = []
    for t in texts:
        if t.isdigit():
            groups.append([t])
        elif groups:
            groups[-1].append(t)
        else:
            # label text before any code token seen -- stray banner fragment
            continue

    results = []
    for group in groups:
        code, *label_tokens = group
        label = " ".join(label_tokens)
        if not label:
            continue
        results.append({"code": code, "label": label})
    return results


def parse_codebook() -> tuple[list[dict], list[str]]:
    entries: dict[str, dict] = {}
    warnings: list[str] = []

    with pdfplumber.open(str(PDF_PATH)) as pdf:
        for page_num in range(FIRST_CONTENT_PAGE, LAST_CONTENT_PAGE + 1):
            page = pdf.pages[page_num]
            words = [w for w in page.extract_words(use_text_flow=False) if w["top"] < FOOTER_TOP_CUTOFF]
            for row in group_rows(words):
                for zone in split_zones(row):
                    for parsed in parse_zone(zone):
                        code, label = parsed["code"], parsed["label"]
                        if code in entries and entries[code]["label"] != label:
                            warnings.append(
                                f"page {page_num}: code {code} already seen as "
                                f"{entries[code]['label']!r} (page {entries[code]['source_page']}), "
                                f"now {label!r} -- keeping first"
                            )
                            continue
                        if code in entries:
                            continue
                        side = "receipts" if code[0] in "12345" else "payments"
                        entries[code] = {
                            "code": code,
                            "label": label,
                            "side": side,
                            "level": len(code),
                            "parent": code[:-1] if len(code) > 1 else None,
                            "source_page": page_num,
                        }

    for code, label in LEVEL1_LABEL_OVERRIDES.items():
        if code in entries:
            entries[code]["label"] = label
        else:
            entries[code] = {
                "code": code,
                "label": label,
                "side": "receipts" if code[0] in "12345" else "payments",
                "level": 1,
                "parent": None,
                "source_page": 11,  # page11's chapter-title banner (see comment above)
            }

    ordered = sorted(entries.values(), key=lambda e: (e["side"], e["code"]))
    return ordered, warnings


def parse_suffix_codebook() -> tuple[list[dict], list[str]]:
    """Parse the suffix-code pages (SUFFIX_PAGE_SIDES) into the orthogonal
    suffix-code namespace. Kept in a separate output file from
    parse_codebook()'s main tree: suffix codes collide with main-tree code
    strings (e.g. "21" is a main-tree code AND an unrelated receipts-suffix
    code), and reuse the same 1-9 digits once per side, so entries here are
    keyed by (side, suffix_code), not by suffix_code alone.
    """
    entries: dict[tuple[str, str], dict] = {}
    warnings: list[str] = []

    with pdfplumber.open(str(PDF_PATH)) as pdf:
        for page_num, side in SUFFIX_PAGE_SIDES.items():
            page = pdf.pages[page_num]
            words = [w for w in page.extract_words(use_text_flow=False) if w["top"] < FOOTER_TOP_CUTOFF]
            for row in group_rows(words):
                for zone in split_zones(row):
                    for parsed in parse_zone(zone):
                        code, label = parsed["code"], parsed["label"]
                        key = (side, code)
                        if key in entries and entries[key]["label"] != label:
                            warnings.append(
                                f"page {page_num}: suffix code {code} ({side}) already seen as "
                                f"{entries[key]['label']!r} (page {entries[key]['source_page']}), "
                                f"now {label!r} -- keeping first"
                            )
                            continue
                        if key in entries:
                            continue
                        entries[key] = {
                            "suffix_code": code,
                            "label": label,
                            "side": side,
                            "level": len(code),
                            "parent": code[:-1] if len(code) > 1 else None,
                            "source_page": page_num,
                        }

    for (side, code), label in SUFFIX_LABEL_OVERRIDES.items():
        key = (side, code)
        if key in entries:
            entries[key]["label"] = label
        else:
            entries[key] = {
                "suffix_code": code,
                "label": label,
                "side": side,
                "level": len(code),
                "parent": code[:-1] if len(code) > 1 else None,
                "source_page": min(p for p, s in SUFFIX_PAGE_SIDES.items() if s == side),
            }

    ordered = sorted(entries.values(), key=lambda e: (e["side"], e["suffix_code"]))
    return ordered, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", help="comma-separated codes to print and exit, e.g. 631,111")
    args = parser.parse_args()

    entries, warnings = parse_codebook()
    by_code = {e["code"]: e for e in entries}

    if args.check:
        for code in args.check.split(","):
            code = code.strip()
            print(f"{code}: {by_code.get(code, 'NOT FOUND')}")
        return

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Parsed {len(entries)} codes from pages {FIRST_CONTENT_PAGE}-{LAST_CONTENT_PAGE}")
    receipts = sum(1 for e in entries if e["side"] == "receipts")
    payments = sum(1 for e in entries if e["side"] == "payments")
    print(f"  receipts: {receipts}  payments: {payments}")
    by_level: dict[int, int] = {}
    for e in entries:
        by_level[e["level"]] = by_level.get(e["level"], 0) + 1
    print(f"  by level (digit count): {dict(sorted(by_level.items()))}")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  {w}")
    print(f"\nWritten to {OUTPUT_PATH}")

    suffix_entries, suffix_warnings = parse_suffix_codebook()
    SUFFIX_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUFFIX_OUTPUT_PATH.write_text(
        json.dumps(suffix_entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nParsed {len(suffix_entries)} suffix codes from pages {sorted(SUFFIX_PAGE_SIDES)}")
    if suffix_warnings:
        print(f"\n{len(suffix_warnings)} suffix warning(s):")
        for w in suffix_warnings:
            print(f"  {w}")
    print(f"Written to {SUFFIX_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
