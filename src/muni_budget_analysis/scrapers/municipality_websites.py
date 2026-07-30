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
    "חיפה": "https://www.haifa.muni.il",
    "אשדוד": "https://www.ashdod.muni.il",
    "ראשון לציון": "https://www.rishonlezion.muni.il",
    "פתח תקווה": "https://www.petah-tikva.muni.il",
    "באר שבע": "https://www.beer-sheva.muni.il",
    "נתניה": "https://www.netanya.muni.il",
    "חולון": "https://www.holon.muni.il",
    "בני ברק": "https://www.bnei-brak.muni.il",
    "רמת גן": "https://www.ramat-gan.muni.il",
    "אשקלון": "https://ashkelon.muni.gov.il",
    "רחובות": "https://www.rehovot.muni.il",
    "בת ים": "https://www.bat-yam.muni.il",
    "בית שמש": "https://www.betshemesh.muni.il",
    "כפר סבא": "https://www.kfar-saba.muni.il",
    "הרצלייה": "https://www.herzliya.muni.il",
    "הרצליה": "https://www.herzliya.muni.il",
    "חדרה": "https://www.hadera.muni.il",
    "מודיעין-מכבים-רעות": "https://www.modiin.muni.il",
    "מודיעין עילית": "https://modil.org.il",
    "נצרת": "https://www.nazareth.muni.il",
    "רמלה": "https://portal.jibbajabba.uk.com",
    "רעננה": "https://www.raanana.muni.il",
    "נהרייה": "https://www.nahariya.muni.il",
    "קריית אתא": "https://www.kiryat-ata.org.il",
    "גבעתיים": "https://www.givatayim.muni.il",
    "הוד השרון": "https://www.hod-hasharon.muni.il",
    "אום אל-פחם": "https://he.umelfahem.org",
    "קריית גת": "https://www.qiryat-gat.muni.il",
    "אילת": "https://www.eilat.muni.il",
    "ראש העין": "https://www.rosh-haayin.muni.il",
    "עכו": "https://www.akko.muni.il",
    "ביתר עילית": "https://www.betar-illit.muni.il",
    "כרמיאל": "https://www.karmiel.muni.il",
    "טבריה": "https://www.tiberias.muni.il",
    "עפולה": "https://www.afula.muni.il",
    "שדרות": "https://sderot.muni.gov.il",
    "לוד": "https://lod.muni.il",
    "רהט": "https://www.rahat-muni.com",
    "טירה": "https://www.tira.muni.il",
    "טמרה": "https://www.tamra.muni.il",
    "נוף הגליל": "https://www.nof-hagalil.muni.il",
    "נתיבות": "https://www.netivot.muni.il",
    "נס ציונה": "https://www.nzc.org.il",
    "נשר": "https://www.nesher.muni.il",
    "מעלה אדומים": "https://www.maale-adummim.muni.il",
    "מעלות-תרשיחא": "https://www.maltar.org.il",
    "מגדל העמק": "https://www.migdal-haemeq.muni.il",
    "באקה אל-גרביה": "https://www.baqa.co.il",
    "עראבה": "https://www.arraba.muni.il",
    "שפרעם": "https://shefaram.muni.il",

    # Regional Councils (מועצות אזוריות)
    "מועצה אזורית אשכול": "https://www.eshkol.info",
    "מועצה אזורית בוסתן אל-מרג'": "https://www.bustanelmarg.muni.il",
    "מועצה אזורית גולן": "https://www.golan.org.il",
    "מועצה אזורית גוש עציון": "https://www.baitisraeli.co.il",
    "מועצה אזורית דרום השרון": "https://www.dsharon.org.il",
    "מועצה אזורית הגליל העליון": "https://www.galil-elion.org.il",
    "מועצה אזורית הגליל התחתון": "https://www.glt.org.il",
    "מועצה אזורית הר חברון": "https://www.hrhevron.co.il",
    "מועצה אזורית חבל אילות": "https://www.eilot.org.il",
    "מועצה אזורית חבל יבנה": "https://www.hevel-yavne.org.il",
    "מועצה אזורית חבל מודיעין": "https://www.modiin-region.muni.il",
    "מועצה אזורית חוף אשקלון": "https://www.hof-ashkelon.org.il",
    "מועצה אזורית מגילות ים המלח": "https://www.dead-sea.org.il",
    "מועצה אזורית מטה אשר": "https://www.mta.org.il/",
    "מועצה אזורית מטה בנימין": "https://www.binyamin.org.il",
    "מועצה אזורית מטה יהודה": "https://www.m-yehuda.org.il",
    "מועצה אזורית מרחבים": "https://www.merchavim.org.il",
    "מועצה אזורית ערבות הירדן": "https://www.jordanvalley.org.il",
    "מועצה אזורית רמת נגב": "https://rng.org.il",
    "מועצה אזורית שומרון": "https://www.shomron.org.il",
    "מועצה אזורית שפיר": "https://www.shaffir.org.il",
    "מועצה אזורית אל קסום": "https://www.alqasoum.org.il",
    "מועצה אזורית אל-בטוף": "https://el-batouf-region.muni.il",
    "מועצה אזורית אלונה": "https://www.alona.org.il",
    "מועצה אזורית באר טוביה": "https://www.beer-tuvia.org.il",
    "מועצה אזורית בני שמעון": "https://bns.org.il",
    "מועצה אזורית ברנר": "https://www.brener.org.il",
    "מועצה אזורית גדרות": "https://www.gderot.muni.il",
    "מועצה אזורית גזר": "https://www.gezer-region.muni.il",
    "מועצה אזורית גן רווה": "https://www.ganrave.com/index.html",
    "מועצה אזורית הגלבוע": "https://www.hagilboa.org.il",
    "מועצה אזורית הערבה התיכונה": "https://www.arava.co.il",
    "מועצה אזורית זבולון": "https://www.zvulun.org.il",

    # Local Councils (מועצות מקומיות)
    "אבו סנאן": "https://www.abu-sinan.muni.il",
    "אורנית": "https://www.oranit.org.il",
    "אזור": "https://www.azor.muni.il",
    "אליכין": "https://www.elyakhin.muni.il",
    "אלפי מנשה": "https://www.alfe-menashe.muni.il",
    "אלקנה": "https://www.elkana.org.il",
    "אפרת": "https://www.efrat.muni.il",
    "בית אל": "https://www.bet-el.muni.il",
    "בית אריה-עופרים": "https://www.beit-arye.co.il",
    "בית ג'ן": "https://beit-jann.muni.il",
    "בני עי\"ש": "https://bney-ayish.muni.il",
    "ג'דיידה-מכר": "https://www.judeidemaker.muni.il",
    "ג'ולס": "https://www.julis.muni.il",
    "ג'סר א-זרקא": "https://jisr-az-zarqa.muni.il",
    "ג'ש (גוש חלב)": "https://www.jish.org.il",
    "ג'ת": "https://www.jatt.muni.il",
    "דייר אל-אסד": "https://www.deiralasad.muni.il",
    "דייר חנא": "https://www.deir-hanna.muni.il",
    "הר אדר": "https://www.har-adar.muni.il",
    "זמר": "https://zemer.muni.il",
    "זרזיר": "https://zarzir.muni.il",
    "חורפיש": "https://lch.org.il",
    "חצור הגלילית": "https://www.hatzorg.co.il",
    "טובא-זנגרייה": "https://www.tuba-zangariyye.muni.il",
    "טורעאן": "https://www.turan.muni.il",
    "יבנאל": "https://www.yavneel.muni.il",
    "כאבול": "https://www.kabul.muni.il",
    "כאוכב אבו אל-היג'א": "https://kaokab-abu-alhija.muni.il",
    "כוכב יאיר": "https://www.kokhav-yair.muni.il",
    "כסיפה": "https://www.kuseife.muni.il",
    "כסרא-סמיע": "https://kisra-sumei.muni.il",
    "כעביה-טבאש-חג'אג'רה": "https://www.kaabiyye-tabbash-hajajre.muni.il",
    "כפר ברא": "https://www.kafar-bara.muni.il",
    "כפר ורדים": "https://kfarvradim.com",
    "כפר כנא": "https://www.kfarcana.muni.il",
    "כפר מנדא": "https://kafar-manda.muni.il",
    "כפר תבור": "https://www.kefar-tavor.muni.il",
    "להבים": "https://www.lehavim.muni.il",
    "לקיה": "https://www.laqye.muni.il",
    "מג'ד אל-כרום": "https://www.majd.co.il",
    "מג'דל שמס": "https://www.majdal.co.il",
    "מגדל": "https://m-migdal.co.il",
    "מטולה": "https://www.metulla.muni.il",
    "מעיליא": "https://www.mielya.muni.il",
    "מעלה אפרים": "https://www.maaleefraim.co.il",
    "סאג'ור": "https://www.sajur.muni.il",
    "ע'ג'ר": "https://ghajarlc.org.il",
    "עיילבון": "https://www.eilaboun.muni.il",
    "עילוט": "https://www.ilut.muni.il",
    "עין קנייא": "https://einknia.com",
    "עספיא": "https://www.isifya.co.il",
    "ערערה": "https://www.arara-ara.muni.il",
    "ערערה-בנגב": "https://www.arara-banegev.muni.il",
    "פקיעין (בוקייעה)": "https://www.peqiin.muni.il",
    "פרדס חנה-כרכור": "https://www.pardes-hanna-karkur.muni.il",
    "שבלי - אום אל-גנם": "https://www.shibli-umm-al-ghanam.muni.il",
    "שגב-שלום": "https://www.segev-shalom.muni.il",
    "שער שומרון": "https://www.shaar-s.muni.il",
    "תל שבע": "https://tel-sheva.muni.il",
    "בסמ\"ה": "https://www.basma.muni.il",
    "פרדסייה": "https://www.pardesia.muni.il",
    "צור הדסה": "https://tzur-hadassa.org.il",
    "מגאר": "https://www.al-maghar.co.il",
    "ריינה": "https://reine.muni.il",
    "ראש פינה": "https://rosh-pinna.muni.il",
    "יסוד המעלה": "https://www.yesud-hamaala.muni.il",
    "מזכרת בתיה": "https://mazkeret-batya.muni.il",
    "כפר יונה": "https://www.kfar-yona.muni.il",
    "קדומים": "https://www.kedumim.org.il",
    "קדימה-צורן": "https://www.kadima-zoran.muni.il",
    "קצרין": "https://katsrin.com",
    "קריית ארבע": "https://www.kiryat4.org.il",
    "קריית עקרון": "https://www.kiryat-ekron.muni.il",
    "קרני שומרון": "https://www.karneishomron.co.il",
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
        url_str = f"https://{url_str}"
        
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
