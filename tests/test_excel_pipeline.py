import sys
import unittest
from pathlib import Path

# Ensure 'src' is in sys.path when running tests directly
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEL_AVIV_XLSX = PROJECT_ROOT / "budget_examples" / "tel_aviv_2026.xlsx"
ELAD_XLSX = PROJECT_ROOT / "budget_examples" / "elad_2022.xlsx"

from muni_budget_analysis.processing.excel_pipeline import (
    segment_sheet_tables,
    extract_excel_tables,
)


class TestSegmentSheetTablesSynthetic(unittest.TestCase):
    """
    Real correctness test: build an in-memory workbook with two clearly
    separated regions (rows 1-3 filled, rows 4-5 blank, rows 6-8 filled)
    and verify segment_sheet_tables detects exactly 2 regions with the
    right row bounds.
    """

    def test_two_regions_detected(self):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active

        for row in (1, 2, 3):
            ws.cell(row=row, column=1, value=f"a{row}")
            ws.cell(row=row, column=2, value=f"b{row}")

        # rows 4-5 left blank

        for row in (6, 7, 8):
            ws.cell(row=row, column=1, value=f"a{row}")
            ws.cell(row=row, column=3, value=f"c{row}")

        regions = segment_sheet_tables(ws)

        self.assertEqual(len(regions), 2)

        self.assertEqual(regions[0]["min_row"], 1)
        self.assertEqual(regions[0]["max_row"], 3)
        self.assertEqual(regions[0]["min_col"], 1)
        self.assertEqual(regions[0]["max_col"], 2)

        self.assertEqual(regions[1]["min_row"], 6)
        self.assertEqual(regions[1]["max_row"], 8)
        self.assertEqual(regions[1]["min_col"], 1)
        self.assertEqual(regions[1]["max_col"], 3)

    def test_empty_sheet_returns_no_regions(self):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active

        regions = segment_sheet_tables(ws)

        self.assertEqual(regions, [])


class TestRealSamplesSmoke(unittest.TestCase):
    """
    Smoke tests against real sample workbooks -- there's no ground-truth
    expected output for these files yet, so these only assert the pipeline
    runs without crashing and produces at least one non-empty region per
    file. Fidelity (correct cell values/bounds) is NOT asserted here.
    """

    def _assert_smoke(self, path: Path):
        self.assertTrue(path.exists(), f"missing sample file: {path}")

        result = extract_excel_tables(path)

        self.assertIn("sheets", result)
        self.assertGreaterEqual(len(result["sheets"]), 1)

        total_regions = 0
        for sheet in result["sheets"]:
            for region in sheet["regions"]:
                total_regions += 1
                self.assertGreater(len(region["rows"]), 0)

        self.assertGreaterEqual(total_regions, 1)

    def test_tel_aviv_2026_smoke(self):
        self._assert_smoke(TEL_AVIV_XLSX)

    def test_elad_2022_smoke(self):
        self._assert_smoke(ELAD_XLSX)


class TestRealSamplesFidelity(unittest.TestCase):
    """
    Ground-truth fidelity check against real sample workbooks: unlike
    TestRealSamplesSmoke (crash-only), these assert extracted cell text and
    segmentation bounds match values read directly from the source files
    (verified independently via openpyxl against the raw .xlsx).
    """

    def test_elad_2022_single_continuous_region(self):
        result = extract_excel_tables(ELAD_XLSX)

        self.assertEqual(len(result["sheets"]), 1)
        sheet = result["sheets"][0]
        self.assertEqual(len(sheet["regions"]), 1)

        region = sheet["regions"][0]
        self.assertEqual(region["min_row"], 1)
        self.assertEqual(len(region["rows"]), 625)  # whole sheet, no blank-row gaps

        header_row = region["rows"][0]
        self.assertEqual(
            [c["text"] for c in header_row],
            ["מס כרטיס", "שם כרטיס", "מספר משרות", "תקציב באלפי שח"],
        )
        self.assertTrue(all(c["is_header"] for c in header_row))

        first_data_row = region["rows"][1]
        self.assertEqual(
            [c["text"] for c in first_data_row],
            ["1111100100", "ארנונה מגורים", "0", "44500"],
        )
        self.assertFalse(any(c["is_header"] for c in first_data_row))

        # no merged cells anywhere in this file -> every cell is a plain 1x1 span
        self.assertTrue(all(
            c["row_span"] == 1 and c["col_span"] == 1
            for row in region["rows"] for c in row
        ))

    def test_tel_aviv_2026_income_sheet_known_values(self):
        result = extract_excel_tables(TEL_AVIV_XLSX)
        sheets = {s["sheet_name"]: s for s in result["sheets"]}
        region = sheets["הכנסות"]["regions"][0]

        self.assertEqual(region["min_row"], 1)
        self.assertEqual(len(region["rows"]), 397)

        # Row 1 is a single-cell title banner ("הצעת תקציב רגיל..."), not the
        # real column-header row -- segment_sheet_tables' gap heuristic can't
        # tell the two apart (both just look like "a non-empty row" to it), so
        # is_header ends up on the banner instead of row 2's actual column
        # names. Known gap per ADR-0002 / PR #5, not fixed here -- asserted
        # explicitly so a future fix has a test to flip instead of this
        # passing silently on the wrong row.
        title_row = region["rows"][0]
        self.assertEqual(
            title_row[0]["text"], "הצעת תקציב רגיל \nלשנת הכספים תשפ\"ג  2023\nהכנסות"
        )
        self.assertTrue(title_row[0]["is_header"])

        real_header_row = region["rows"][1]
        self.assertEqual(real_header_row[0]["text"], "פרק")
        self.assertEqual(real_header_row[3]["text"], "שם סעיף")
        self.assertFalse(real_header_row[0]["is_header"])

        first_data_row = region["rows"][2]
        self.assertEqual(first_data_row[0]["text"], "11000")
        self.assertEqual(first_data_row[2]["text"], "11000/121/8")
        self.assertEqual(first_data_row[3]["text"], "גביה שוטפת-מגורים")
        self.assertEqual(first_data_row[4]["text"], "1320000000")


if __name__ == "__main__":
    unittest.main()
