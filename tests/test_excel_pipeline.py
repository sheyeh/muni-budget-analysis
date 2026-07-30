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


if __name__ == "__main__":
    unittest.main()
