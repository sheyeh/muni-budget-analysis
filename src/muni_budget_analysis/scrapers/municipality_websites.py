#!/usr/bin/env python3
"""
municipality_websites.py

Scraper to find and extract official website URLs for all Israeli local municipalities
(Cities, Local Councils, and Regional Councils).

Coverage Strategy:
- Curated Registry for official municipal domain URLs in Israel.
- Wikidata SPARQL Bulk Query for open-data entity mapping.
- Wikipedia Search API & Infobox Parsing.
- Multi-threaded execution.

Outputs:
- data/localities/municipality_websites.json
- data/localities/municipality_websites.csv
"""

import argparse
import csv
import json
import logging
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure 'src' is in sys.path when running script directly
SRC_DIR = Path(__file__).resolve().parents[2]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "localities"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) MuniBudgetAnalysis/1.0"
}

# Complete official website registry for Israeli local authorities
KNOWN_MUNICIPAL_WEBSITES = {
    # Cities (עיריות)
    "תל אביב -יפו": "https://www.tel-aviv.gov.il",
    "תל אביב-יפו": "https://www.tel-aviv.gov.il",
    "ירושלים": "https://www.jerusalem.muni.il",
    "חיפה": "http://www.haifa.muni.il",
    "אשדוד": "http://www.ashdod.muni.il",
    "ראשון לציון": "http://www.rishonlezion.muni.il",
    "פתח תקווה": "http://www.petah-tikva.muni.il",
    "באר שבע": "http://www.beer-sheva.muni.il",
    "נתניה": "http://www.netanya.muni.il",
    "חולון": "http://www.holon.muni.il",
    "בני ברק": "http://www.bnei-brak.muni.il",
    "רמת גן": "http://www.ramat-gan.muni.il",
    "אשקלון": "http://www.ashkelon.muni.il",
    "רחובות": "http://www.rehovot.muni.il",
    "בת ים": "http://www.bat-yam.muni.il",
    "בית שמש": "http://www.betshemesh.muni.il",
    "כפר סבא": "http://www.kfar-saba.muni.il",
    "הרצלייה": "http://www.herzliya.muni.il",
    "הרצליה": "http://www.herzliya.muni.il",
    "חדרה": "http://www.hadera.muni.il",
    "מודיעין-מכבים-רעות": "http://www.modiin.muni.il",
    "מודיעין עילית": "http://www.modiin-illit.muni.il",
    "נצרת": "http://www.nazareth.muni.il",
    "רמלה": "http://www.ramla.muni.il",
    "רעננה": "http://www.raanana.muni.il",
    "נהרייה": "http://www.nahariya.muni.il",
    "קריית אתא": "http://www.kiryat-ata.muni.il",
    "גבעתיים": "http://www.givatayim.muni.il",
    "הוד השרון": "http://www.hod-hasharon.muni.il",
    "אום אל-פחם": "http://www.um-elfahem.org.il",
    "קריית גת": "http://www.qiryat-gat.muni.il",
    "אילת": "http://www.eilat.muni.il",
    "ראש העין": "http://www.rosh-haayin.muni.il",
    "עכו": "http://www.akko.muni.il",
    "ביתר עילית": "http://www.betar-illit.muni.il",
    "כרמיאל": "http://www.karmiel.muni.il",
    "טבריה": "http://www.tiberias.muni.il",
    "עפולה": "http://www.afula.muni.il",
    "שדרות": "http://www.sderot.muni.il",
    "לוד": "http://www.lod.muni.il",
    "רהט": "http://www.rahat.muni.il",
    "טירה": "http://www.tira.muni.il",
    "טמרה": "http://www.tamra.muni.il",
    "נוף הגליל": "https://www.nof-hagalil.muni.il",
    "נתיבות": "http://www.netivot.muni.il",
    "נס ציונה": "http://www.nzc.org.il",
    "נשר": "http://www.nesher.muni.il",
    "מעלה אדומים": "http://www.maale-adummim.muni.il",
    "מעלות-תרשיחא": "http://www.maalot-tarshiha.muni.il",
    "מגדל העמק": "http://www.migdal-haemeq.muni.il",
    "באקה אל-גרביה": "http://www.baqa.muni.il",
    "עראבה": "http://www.arraba.muni.il",

    # Regional Councils (מועצות אזוריות)
    "מועצה אזורית אשכול": "http://www.eshkol.info",
    "מועצה אזורית בוסתן אל-מרג'": "https://bostanalmarj.co.il",
    "מועצה אזורית גולן": "http://m.e.golan.org.il",
    "מועצה אזורית גוש עציון": "http://www.gush-etzion.org.il",
    "מועצה אזורית דרום השרון": "http://www.dsharon.org.il",
    "מועצה אזורית הגליל העליון": "http://www.galil-elion.org.il",
    "מועצה אזורית הגליל התחתון": "http://www.glt.org.il",
    "מועצה אזורית הר חברון": "http://www.hrhevron.co.il",
    "מועצה אזורית חבל אילות": "http://www.eilot.org.il",
    "מועצה אזורית חבל יבנה": "http://www.hevel-yavne.org.il",
    "מועצה אזורית חבל מודיעין": "http://www.modiin-region.muni.il",
    "מועצה אזורית חוף אשקלון": "http://www.hof-ashkelon.org.il",
    "מועצה אזורית מגילות ים המלח": "http://www.megilot.org.il",
    "מועצה אזורית מטה אשר": "http://www.mateh-asher.org.il",
    "מועצה אזורית מטה בנימין": "http://www.binyamin.org.il",
    "מועצה אזורית מטה יהודה": "http://www.m-yehuda.org.il",
    "מועצה אזורית מרחבים": "http://www.merhavim.org.il",
    "מועצה אזורית ערבות הירדן": "http://www.jordanvalley.org.il",
    "מועצה אזורית רמת נגב": "http://www.ramat-negev.org.il",
    "מועצה אזורית שומרון": "http://www.shomron.org.il",
    "מועצה אזורית שפיר": "http://www.shafir.org.il",
    "מועצה אזורית אל קסום": "http://www.alqasoum.org.il",
    "מועצה אזורית אל-בטוף": "https://el-batouf-region.muni.il",
    "מועצה אזורית אלונה": "http://www.alona.org.il",
    "מועצה אזורית באר טוביה": "http://www.beer-tuvia.org.il",
    "מועצה אזורית בני שמעון": "http://bns.org.il",
    "מועצה אזורית ברנר": "http://www.brener.org.il",
    "מועצה אזורית גדרות": "http://www.gderot.muni.il",
    "מועצה אזורית גזר": "http://www.gezer-region.muni.il",
    "מועצה אזורית גן רווה": "http://www.ganrave.com",
    "מועצה אזורית הגלבוע": "http://www.hagilboa.org.il",
    "מועצה אזורית הערבה התיכונה": "http://www.arava.co.il",
    "מועצה אזורית זבולון": "http://www.zvulun.org.il",

    # Local Councils (מועצות מקומיות)
    "אבו סנאן": "http://www.abu-snan.muni.il",
    "אורנית": "http://www.oranit.org.il",
    "אזור": "http://www.azor.muni.il",
    "אליכין": "http://www.elyakhin.muni.il",
    "אלפי מנשה": "http://www.alfei-menashe.muni.il",
    "אלקנה": "http://www.elkana.muni.il",
    "אפרת": "http://www.efrat.muni.il",
    "בית אל": "http://www.bet-el.muni.il",
    "בית אריה-עופרים": "http://www.beitarye.org.il",
    "בית ג'ן": "http://www.beit-jann.muni.il",
    "בני עי\"ש": "http://www.bney-ayish.muni.il",
    "ג'דיידה-מכר": "http://www.judeideh-maker.muni.il",
    "ג'ולס": "http://www.julis.muni.il",
    "ג'סר א-זרקא": "http://www.jisr-az-zarqa.muni.il",
    "ג'ש (גוש חלב)": "http://www.jish.muni.il",
    "ג'ת": "http://www.jatt.muni.il",
    "דייר אל-אסד": "http://www.deir-al-assad.muni.il",
    "דייר חנא": "http://www.deir-hanna.muni.il",
    "הר אדר": "http://www.har-adar.muni.il",
    "זמר": "http://www.zemer.muni.il",
    "זרזיר": "http://www.zarzir.muni.il",
    "חורפיש": "http://www.hurfeish.muni.il",
    "חצור הגלילית": "http://www.hazor-hagelilit.muni.il",
    "טובא-זנגרייה": "http://www.tuba-zangaria.muni.il",
    "טורעאן": "http://www.tur-an.muni.il",
    "יבנאל": "http://www.yavneel.muni.il",
    "כאבול": "http://www.kabul.muni.il",
    "כאוכב אבו אל-היג'א": "http://www.kaukab.muni.il",
    "כוכב יאיר": "http://www.kyr.org.il",
    "כסיפה": "http://www.kuseife.muni.il",
    "כסרא-סמיע": "http://www.kisra-sumei.muni.il",
    "כעביה-טבאש-חג'אג'רה": "http://www.kaabiyye.muni.il",
    "כפר ברא": "http://www.kfar-bara.muni.il",
    "כפר ורדים": "http://www.varden.muni.il",
    "כפר כנא": "http://www.kfar-kanna.muni.il",
    "כפר מנדא": "http://www.kfar-manda.muni.il",
    "כפר תבור": "http://www.kefar-tavor.muni.il",
    "להבים": "http://www.lehavim.muni.il",
    "לקיה": "http://www.lakiya.muni.il",
    "מג'ד אל-כרום": "http://www.majd-el-kurum.muni.il",
    "מג'דל שמס": "http://www.majdal-shams.muni.il",
    "מגדל": "http://www.migdal.muni.il",
    "מטולה": "http://www.metula.muni.il",
    "מעיליא": "http://www.miilya.muni.il",
    "מעלה אפרים": "http://www.maale-ephraim.muni.il",
    "סאג'ור": "http://www.sajur.muni.il",
    "ע'ג'ר": "http://.muni.il",
    "עיילבון": "http://www.eilabun.muni.il",
    "עילוט": "http://www.ilut.muni.il",
    "עין קנייא": "http://www.ein-qiniyye.muni.il",
    "עספיא": "http://www.isfiya.muni.il",
    "ערערה": "http://www.arara.muni.il",
    "ערערה-בנגב": "http://www.arara-banegev.muni.il",
    "פקיעין (בוקייעה)": "http://www.pekiin.muni.il",
    "פרדס חנה-כרכור": "http://www.pardes-hanna-karkur.muni.il",
    "שבלי - אום אל-גנם": "http://www.shibli.muni.il",
    "שגב-שלום": "http://www.segev-shalom.muni.il",
    "שער שומרון": "http://www.shaar-shomron.muni.il",
    "תל שבע": "http://www.tel-sheva.muni.il",
    "בסמ\"ה": "http://www.basma.muni.il",
    "פרדסייה": "http://www.pardessia.muni.il",
    "צור הדסה": "http://www.zur-hadassa.muni.il",
    "מגאר": "http://www.mghar.muni.il",
    "ריינה": "http://www.reineh.muni.il",
    "ראש פינה": "http://www.rosh-pinna.muni.il",
    "יסוד המעלה": "http://www.yesud-hamaala.muni.il",
    "מזכרת בתיה": "http://www.mazkeret-batya.muni.il",
    "כפר יונה": "http://www.kfar-yona.muni.il",
    "קדומים": "http://www.kedumim.org.il",
    "קדימה-צורן": "http://www.kadima-zoran.muni.il",
    "קצרין": "http://www.kazrin.org.il",
    "קריית ארבע": "http://www.kiryat4.org.il",
    "קריית עקרון": "http://www.k-ekron.muni.il",
    "קרני שומרון": "http://www.karnei-shomron.muni.il",
}


def clean_muni_name(name: str) -> str:
    """Normalize whitespace around hyphens and clean name string."""
    cleaned = re.sub(r"\s*-\s*", "-", name).strip()
    return cleaned


def normalize_url(url_str: str) -> Optional[str]:
    """Clean and validate URL format."""
    if not url_str:
        return None
    url_str = url_str.strip()
    url_str = re.sub(r"^[\[\(\"']+|[\]\)\"']+$", "", url_str)
    
    match = re.search(r"https?://[^\s\"'\]\)><]+", url_str)
    if match:
        url_str = match.group(0)
    elif not url_str.startswith(("http://", "https://")):
        url_str = f"http://{url_str}"
        
    url_str = url_str.rstrip("/")
    return url_str if "." in url_str else None


def safe_fetch_json(url: str, retries: int = 2) -> Dict[str, Any]:
    """Safely fetch JSON from URL with retries."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=4) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            pass
    return {}


def fetch_wikidata_bulk_map() -> Dict[str, str]:
    """Fetch all Israeli entities and their official website URLs in 1 SPARQL query."""
    logger.info("Fetching bulk Wikidata SPARQL map for Israeli entities...")
    sparql = """
    SELECT ?itemLabel ?website WHERE {
      ?item wdt:P17 wd:Q801 .
      ?item wdt:P856 ?website .
      ?item rdfs:label ?itemLabel .
      FILTER(LANG(?itemLabel) = "he") .
    }
    """
    url = "https://query.wikidata.org/sparql?query=" + urllib.parse.quote(sparql) + "&format=json"
    wd_map = {}
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for b in data.get("results", {}).get("bindings", []):
                label = b.get("itemLabel", {}).get("value", "").strip()
                site = b.get("website", {}).get("value", "").strip()
                if label and site:
                    norm = normalize_url(site)
                    if norm:
                        wd_map[label] = norm
        logger.info("Loaded %d entity mappings from Wikidata SPARQL.", len(wd_map))
    except Exception as e:
        logger.warning("Wikidata SPARQL bulk fetch failed (%s).", e)
    return wd_map


def resolve_municipality_website(muni: Dict[str, Any], wd_map: Dict[str, str]) -> Dict[str, Any]:
    """
    Pipeline to find the official website for a single municipality.
    """
    raw_name = muni["municipality_name"]
    cname = clean_muni_name(raw_name)
    core = re.sub(r"^(מועצה אזורית|מועצה מקומית|עיריית)\s*", "", cname).strip()
    muni_type = muni["municipality_type"]

    website_url = None
    resolution_source = "not_found"

    # Tier 1: Check Known Registry
    for candidate in [raw_name, cname, core, f"עיריית {core}", f"מועצה מקומית {core}", f"מועצה אזורית {core}"]:
        if candidate in KNOWN_MUNICIPAL_WEBSITES:
            website_url = KNOWN_MUNICIPAL_WEBSITES[candidate]
            resolution_source = "known_registry"
            break

    # Tier 2: Check Wikidata SPARQL Map
    if not website_url:
        candidates = [raw_name, cname, core, f"עיריית {core}", f"מועצה מקומית {core}", f"מועצה אזורית {core}"]
        for candidate in candidates:
            if candidate in wd_map and wd_map[candidate]:
                website_url = wd_map[candidate]
                resolution_source = "wikidata_sparql"
                break

    # Tier 3: Wikipedia API Search
    if not website_url:
        search_queries = [cname, core]
        if muni_type == "עירייה":
            search_queries.append(f"עיריית {core}")
        elif muni_type == "מועצה מקומית":
            search_queries.append(f"מועצה מקומית {core}")
        elif muni_type == "מועצה אזורית" and not cname.startswith("מועצה אזורית"):
            search_queries.insert(0, f"מועצה אזורית {core}")

        for q in search_queries:
            surl = "https://he.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
                "action": "query",
                "list": "search",
                "srsearch": q,
                "format": "json"
            })
            sdata = safe_fetch_json(surl)
            results = sdata.get("query", {}).get("search", [])
            if not results:
                continue

            best_title = results[0]["title"]
            for r in results:
                t = r.get("title", "")
                if t == cname or t == q or t == core:
                    best_title = t
                    break

            purl = "https://he.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
                "action": "query",
                "prop": "pageprops|revisions",
                "ppprop": "wikibase_item",
                "rvprop": "content",
                "rvslots": "main",
                "ellimit": "500",
                "titles": best_title,
                "format": "json"
            })
            pdata = safe_fetch_json(purl)
            pages = pdata.get("query", {}).get("pages", {})
            for pid, page in pages.items():
                if pid == "-1":
                    continue
                content = page.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("*", "")
                if content:
                    infobox_matches = re.findall(r"\|\s*אתר(?:_אינטרנט|_רשמי|\s+אינטרנט|\s+רשמי)?\s*=\s*([^|\n}]+)", content)
                    for match in infobox_matches:
                        url_match = re.search(r"https?://[^\s\]\}|<\"']+", match.strip())
                        if url_match:
                            norm = normalize_url(url_match.group(0))
                            if norm:
                                website_url = norm
                                resolution_source = "wikipedia_infobox"
                                break

                    if not website_url:
                        muni_il_match = re.search(r"https?://[^\s\]\}|<\"']*\.muni\.il[^\s\]\}|<\"']*", content)
                        if muni_il_match:
                            norm = normalize_url(muni_il_match.group(0))
                            if norm:
                                website_url = norm
                                resolution_source = "muni_il_domain"
            if website_url:
                break

    result = dict(muni)
    result["website_url"] = website_url
    result["resolution_source"] = resolution_source
    return result


def scrape_all_municipality_websites(
    municipalities: List[Dict[str, Any]],
    max_workers: int = 15
) -> List[Dict[str, Any]]:
    """
    Scrape official website URLs for a list of municipalities concurrently.
    """
    valid_munis = [m for m in municipalities if m.get("municipality_type") != "חסר מעמד מוניציפלי"]
    total = len(valid_munis)

    wd_map = fetch_wikidata_website_map_bulk()

    logger.info("Resolving websites for %d municipalities using %d threads...", total, max_workers)

    resolved_munis = []
    found_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_muni = {
            executor.submit(resolve_municipality_website, muni, wd_map): muni for muni in valid_munis
        }
        for future in as_completed(future_to_muni):
            try:
                res = future.result()
                resolved_munis.append(res)
                if res.get("website_url"):
                    found_count += 1
            except Exception as e:
                muni = future_to_muni[future]
                logger.error("Error resolving %s: %s", muni.get("municipality_name"), e)
                res = dict(muni)
                res["website_url"] = None
                res["resolution_source"] = "error"
                resolved_munis.append(res)

    resolved_munis.sort(key=lambda m: (m.get("municipality_type", ""), m.get("municipality_name", "")))
    logger.info("Resolution complete! Found websites for %d / %d municipalities (%.1f%%).",
                found_count, total, (found_count / total * 100) if total else 0)
    return resolved_munis


def fetch_wikidata_website_map_bulk() -> Dict[str, str]:
    """Helper alias for bulk Wikidata map."""
    return fetch_wikidata_bulk_map()


def save_websites_json(data: List[Dict[str, Any]], filepath: Path) -> Path:
    """Save resolved municipality websites to JSON."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Saved JSON output to %s", filepath)
    return filepath


def save_websites_csv(data: List[Dict[str, Any]], filepath: Path) -> Path:
    """Save resolved municipality websites to CSV."""
    if not data:
        return filepath
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    flat_data = []
    for m in data:
        row = {
            "municipality_code": m.get("municipality_code"),
            "municipality_name": m.get("municipality_name"),
            "municipality_type": m.get("municipality_type"),
            "website_url": m.get("website_url") or "",
            "resolution_source": m.get("resolution_source") or "",
            "district_name": m.get("district_name") or "",
            "subdistrict_name": m.get("subdistrict_name") or "",
            "total_population": m.get("total_population", 0),
            "num_localities": m.get("num_localities", 0),
        }
        flat_data.append(row)

    fieldnames = list(flat_data[0].keys())
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat_data)

    logger.info("Saved CSV output to %s", filepath)
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Scrape official website URLs for all local municipalities in Israel"
    )
    parser.add_argument(
        "-i", "--input",
        type=Path,
        default=DEFAULT_DATA_DIR / "municipalities.json",
        help="Input municipalities JSON file path"
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Directory to save output files (default: {DEFAULT_DATA_DIR})"
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=15,
        help="Number of concurrent worker threads (default: 15)"
    )

    args = parser.parse_args()

    if not args.input.exists():
        logger.error("Input file %s does not exist. Run localities scraper first.", args.input)
        raise SystemExit(1)

    with open(args.input, "r", encoding="utf-8") as f:
        municipalities = json.load(f)

    resolved = scrape_all_municipality_websites(municipalities, max_workers=args.workers)

    json_path = save_websites_json(resolved, args.output_dir / "municipality_websites.json")
    csv_path = save_websites_csv(resolved, args.output_dir / "municipality_websites.csv")

    print("\n=== Municipality Website Scraping Complete ===")
    print(f"Total Municipalities Processed: {len(resolved)}")
    found_count = len([m for m in resolved if m.get("website_url")])
    print(f"Websites Found:                 {found_count} / {len(resolved)} ({found_count/len(resolved)*100:.1f}%)")
    print(f"JSON Output: {json_path}")
    print(f"CSV Output:  {csv_path}")


if __name__ == "__main__":
    main()
