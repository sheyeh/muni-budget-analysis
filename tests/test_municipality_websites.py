import sys
import unittest
from pathlib import Path

# Ensure 'src' is in sys.path when running tests directly
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from muni_budget_analysis.scrapers.municipality_websites import (
    clean_muni_name,
    normalize_url,
    resolve_municipality_website
)


class TestMunicipalityWebsitesScraper(unittest.TestCase):

    def test_clean_muni_name(self):
        self.assertEqual(clean_muni_name("תל אביב -יפו"), "תל אביב-יפו")
        self.assertEqual(clean_muni_name("מודיעין -מכבים -רעות"), "מודיעין-מכבים-רעות")

    def test_normalize_url(self):
        self.assertEqual(normalize_url("https://www.tel-aviv.gov.il/"), "https://www.tel-aviv.gov.il")
        self.assertEqual(normalize_url("[https://ashdod.muni.il]"), "https://ashdod.muni.il")
        self.assertEqual(normalize_url("www.haifa.muni.il"), "https://www.haifa.muni.il")
        self.assertIsNone(normalize_url("not_a_url"))

    def test_resolve_known_registry(self):
        muni = {
            "municipality_code": 3000,
            "municipality_name": "תל אביב -יפו",
            "municipality_type": "עירייה"
        }
        res = resolve_municipality_website(muni, wd_map={})
        self.assertEqual(res["website_url"], "https://www.tel-aviv.gov.il")
        self.assertEqual(res["resolution_source"], "known_registry")

    def test_resolve_wikidata_sparql(self):
        muni = {
            "municipality_code": 9999,
            "municipality_name": "רשות טסט ייחודית",
            "municipality_type": "עירייה"
        }
        wd_map = {"רשות טסט ייחודית": "https://www.test-muni.muni.il"}
        res = resolve_municipality_website(muni, wd_map=wd_map)
        self.assertEqual(res["website_url"], "https://www.test-muni.muni.il")
        self.assertEqual(res["resolution_source"], "wikidata_sparql")


if __name__ == "__main__":
    unittest.main()
