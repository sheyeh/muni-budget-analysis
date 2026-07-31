import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muni_budget_analysis.scrapers.budget_files import (
    determine_file_type,
    extract_years_from_text,
    is_strict_budget_document
)


class TestBudgetFilesScraper(unittest.TestCase):

    def test_is_strict_budget_document(self):
        # Valid budget documents
        self.assertTrue(is_strict_budget_document("תקציב 2024", "https://example.com/budget2024.pdf"))
        self.assertTrue(is_strict_budget_document("ספר תקציב רגיל לשנת 2025", "https://example.com/book.xlsx"))
        self.assertTrue(is_strict_budget_document("תקציב רגיל ותב\"ר 2023", "https://example.com/tbar.pdf"))

        # Irrelevant non-budget documents (FOI, accessibility, forms, development budgets)
        self.assertFalse(is_strict_budget_document("תקציב פיתוח 2023", "https://example.com/ptuach.pdf"))
        self.assertFalse(is_strict_budget_document("דיווח ממונה על חוק חופש המידע 2024", "https://example.com/foi.pdf"))
        self.assertFalse(is_strict_budget_document("בקשה להנגשה פיזית במוסד חינוכי", "https://example.com/form.pdf"))
        self.assertFalse(is_strict_budget_document("טופס ארנונה לשנת 2024", "https://example.com/form.pdf"))

    def test_determine_file_type(self):
        self.assertEqual(determine_file_type("https://example.com/budget.xlsx", "תקציב"), "excel")
        self.assertEqual(determine_file_type("https://example.com/budget.csv", "CSV"), "excel")
        self.assertEqual(determine_file_type("https://example.com/budget.pdf", "ספר תקציב PDF"), "pdf")
        self.assertEqual(determine_file_type("https://online.fliphtml5.com/abc/def/", "ספר דיגיטלי"), "fliphtml")
        self.assertIsNone(determine_file_type("https://example.com/index.html", "דף ראשי"))

    def test_extract_years_from_text(self):
        self.assertEqual(extract_years_from_text("תקציב לשנת 2024 ושינויי 2023"), [2024, 2023])
        self.assertEqual(extract_years_from_text("budget_2022_final.pdf"), [2022])
        self.assertEqual(extract_years_from_text("no year here"), [])


if __name__ == "__main__":
    unittest.main()
