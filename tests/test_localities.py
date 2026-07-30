import sys
import unittest
from pathlib import Path

# Ensure 'src' is in sys.path when running tests directly
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muni_budget_analysis.scrapers.localities import (
    clean_locality_record,
    aggregate_municipalities,
    extract_year_from_string
)


class TestLocalitiesScraper(unittest.TestCase):

    def test_extract_year(self):
        self.assertEqual(extract_year_from_string("קובץ היישובים 2023"), 2023)
        self.assertEqual(extract_year_from_string("bycode2022.xlsx"), 2022)
        self.assertIsNone(extract_year_from_string("no_year_here"))

    def test_clean_locality_record(self):
        raw = {
            "סמל יישוב": 3000,
            "שם יישוב": "ירושלים",
            "שם יישוב באנגלית": "Jerusalem",
            "תעתיק": "JERUSALEM",
            "סמל מחוז": 1,
            "שם מחוז": "ירושלים",
            "סמל מעמד מונציפאלי": 0,
            "שם מעמד מונציפאלי": "עירייה",
            "סך הכל אוכלוסייה 2023 - ארעי": 984500,
        }
        cleaned = clean_locality_record(raw)
        self.assertEqual(cleaned["locality_code"], 3000)
        self.assertEqual(cleaned["locality_name_he"], "ירושלים")
        self.assertEqual(cleaned["locality_name_en"], "Jerusalem")
        self.assertEqual(cleaned["population"], 984500)
        self.assertEqual(cleaned["municipal_status_name"], "עירייה")

    def test_aggregate_municipalities(self):
        localities = [
            {
                "locality_code": 3000,
                "locality_name_he": "ירושלים",
                "locality_name_en": "Jerusalem",
                "district_name": "ירושלים",
                "subdistrict_name": "ירושלים",
                "cluster": "",
                "municipal_status_name": "עירייה",
                "municipal_status_code": 0,
                "population": 984500,
            },
            {
                "locality_code": 7,
                "locality_name_he": "שחר",
                "locality_name_en": "Shahar",
                "district_name": "הדרום",
                "subdistrict_name": "אשקלון",
                "cluster": "",
                "municipal_status_name": "מועצה אזורית לכיש",
                "municipal_status_code": 50,
                "population": 812,
            }
        ]

        munis = aggregate_municipalities(localities)
        self.assertEqual(len(munis), 2)
        muni_names = [m["municipality_name"] for m in munis]
        self.assertIn("ירושלים", muni_names)
        self.assertIn("מועצה אזורית לכיש", muni_names)


if __name__ == "__main__":
    unittest.main()
