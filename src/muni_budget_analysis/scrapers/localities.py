#!/usr/bin/env python3
"""
localities.py

Scrapes and extracts a comprehensive list of Israeli localities and local municipalities
from data.gov.il: https://data.gov.il/he/datasets/lamas/localities-in-israel

Features:
- Dynamically queries the official data.gov.il CKAN API for dataset metadata.
- Scrapes all localities using the CKAN Datastore API with automatic pagination.
- Aggregates localities into comprehensive Local Municipalities (Cities, Local Councils, Regional Councils).
- Saves raw dataset files, localities, and municipalities in JSON and CSV formats.
"""

import argparse
import csv
import json
import logging
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure 'src' is in sys.path when running script directly
SRC_DIR = Path(__file__).resolve().parents[2]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

DATASET_ID = "localities-in-israel"
CKAN_PACKAGE_URL = f"https://data.gov.il/api/3/action/package_show?id={DATASET_ID}"
CKAN_DATASTORE_URL = "https://data.gov.il/api/3/action/datastore_search"

# Point to project_root / data / localities
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "localities"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def fetch_dataset_metadata(dataset_id: str = DATASET_ID) -> Dict[str, Any]:
    """Fetch metadata for a dataset from the data.gov.il CKAN API."""
    url = f"https://data.gov.il/api/3/action/package_show?id={dataset_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    logger.info("Fetching dataset metadata from %s...", url)
    with urllib.request.urlopen(req) as response:
        if response.status != 200:
            raise RuntimeError(f"API request failed with HTTP status {response.status}")
        content = response.read().decode("utf-8")
        data = json.loads(content)
        if not data.get("success"):
            raise RuntimeError("CKAN API returned success=False")
        return data["result"]


def extract_year_from_string(text: str) -> Optional[int]:
    """Extract a 4-digit year (e.g., 2023) from text or filename."""
    match = re.search(r"(?:^|\D)(20\d{2})(?:\D|$)", text)
    return int(match.group(1)) if match else None


def select_latest_resource(resources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Find the latest resource from the CKAN package resource list.
    Evaluates year in name/url, created/modified timestamps, and resource position.
    """
    if not resources:
        raise ValueError("No resources found in dataset package metadata.")

    def sort_key(res: Dict[str, Any]) -> Tuple[int, str]:
        name = res.get("name", "")
        url = res.get("url", "")
        year = extract_year_from_string(name) or extract_year_from_string(url) or 0
        timestamp = res.get("last_modified") or res.get("created") or ""
        return (year, timestamp)

    sorted_resources = sorted(resources, key=sort_key, reverse=True)
    latest = sorted_resources[0]
    logger.info("Selected latest resource: '%s' (ID: %s)", latest.get("name"), latest.get("id"))
    return latest


def scrape_datastore_records(resource_id: str, batch_size: int = 500) -> List[Dict[str, Any]]:
    """
    Scrape all records from data.gov.il datastore API with pagination.
    """
    records = []
    offset = 0
    total = None

    logger.info("Scraping records from Datastore API for resource ID: %s...", resource_id)
    while True:
        url = f"{CKAN_DATASTORE_URL}?resource_id={resource_id}&limit={batch_size}&offset={offset}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Datastore query failed with status {resp.status}")
            data = json.loads(resp.read().decode("utf-8"))
            if not data.get("success"):
                raise RuntimeError("Datastore API returned success=False")
            
            result = data["result"]
            total = result.get("total", 0)
            batch = result.get("records", [])
            records.extend(batch)
            
            logger.info("Fetched %d records (total: %d/%d)", len(batch), len(records), total)
            if len(records) >= total or not batch:
                break
            offset += batch_size

    logger.info("Successfully scraped %d total records.", len(records))
    return records


def download_raw_file(url: str, destination_path: Path) -> Path:
    """Download a file from URL to destination path."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading file from %s to %s...", url, destination_path)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as response, open(destination_path, "wb") as out_file:
        out_file.write(response.read())
    logger.info("Download completed (%d bytes).", destination_path.stat().st_size)
    return destination_path


def parse_population(record: Dict[str, Any]) -> int:
    """Safely extract population integer from a record."""
    for key, val in record.items():
        if key and "סך הכל אוכלוסייה" in str(key):
            try:
                return int(val) if val is not None else 0
            except (ValueError, TypeError):
                return 0
    return 0


def clean_locality_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Standardize locality record keys and clean up values."""
    return {
        "locality_code": record.get("סמל יישוב"),
        "locality_name_he": (record.get("שם יישוב") or "").strip(),
        "locality_name_en": (record.get("שם יישוב באנגלית") or "").strip(),
        "transliteration": (record.get("תעתיק") or "").strip(),
        "district_code": record.get("סמל מחוז"),
        "district_name": (record.get("שם מחוז") or "").strip(),
        "subdistrict_code": record.get("סמל נפה"),
        "subdistrict_name": (record.get("שם נפה") or "").strip(),
        "natural_area": record.get("אזור טבעי"),
        "municipal_status_code": record.get("סמל מעמד מונציפאלי"),
        "municipal_status_name": (record.get("שם מעמד מונציפאלי") or "").strip(),
        "population": parse_population(record),
        "year_founded": record.get("שנת ייסוד"),
        "coordinates": record.get("קואורדינטות"),
        "elevation_m": record.get("גובה ממוצע עודכון בתאריך 12/02/2025"),
        "planning_committee": record.get("ועדת תכנון"),
        "police_station": record.get("תחנת משטרה"),
        "year": record.get("שנה"),
        "cluster": (record.get("אשכול רשויות מקומיות") or "").strip(),
    }


def aggregate_municipalities(localities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Group localities into comprehensive local municipalities (Cities, Local Councils, Regional Councils).
    """
    muni_dict: Dict[str, Dict[str, Any]] = {}

    for loc in localities:
        status_name = loc["municipal_status_name"]
        status_code = loc["municipal_status_code"]
        locality_name = loc["locality_name_he"]
        locality_code = loc["locality_code"]

        if status_name == "עירייה":
            muni_key = f"city_{locality_code}"
            muni_name = locality_name
            muni_type = "עירייה"
            muni_code = locality_code
        elif status_name == "מועצה מקומית":
            muni_key = f"council_{locality_code}"
            muni_name = locality_name
            muni_type = "מועצה מקומית"
            muni_code = locality_code
        elif status_name.startswith("מועצה אזורית"):
            muni_key = f"regional_{status_code}"
            muni_name = status_name
            muni_type = "מועצה אזורית"
            muni_code = status_code
        else:
            muni_key = "unassigned"
            muni_name = "חסר מעמד מוניציפלי"
            muni_type = "חסר מעמד מוניציפלי"
            muni_code = 0

        if muni_key not in muni_dict:
            muni_dict[muni_key] = {
                "municipality_code": muni_code,
                "municipality_name": muni_name,
                "municipality_type": muni_type,
                "district_name": loc["district_name"],
                "subdistrict_name": loc["subdistrict_name"],
                "cluster": loc["cluster"],
                "total_population": 0,
                "num_localities": 0,
                "localities": [],
            }

        muni_dict[muni_key]["total_population"] += loc["population"]
        muni_dict[muni_key]["num_localities"] += 1
        muni_dict[muni_key]["localities"].append({
            "locality_code": loc["locality_code"],
            "locality_name_he": loc["locality_name_he"],
            "locality_name_en": loc["locality_name_en"],
            "population": loc["population"],
        })

    # Convert to list sorted by type and name
    municipalities = list(muni_dict.values())
    municipalities.sort(key=lambda m: (m["municipality_type"], m["municipality_name"]))
    return municipalities


def save_json(data: Any, filepath: Path) -> Path:
    """Save python object as formatted JSON."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Saved JSON data to %s", filepath)
    return filepath


def save_csv(data: List[Dict[str, Any]], filepath: Path) -> Path:
    """Save list of dicts to CSV file."""
    if not data:
        return filepath
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    # Flatten nested structures (e.g. localities list inside municipality)
    flat_data = []
    for item in data:
        row = {}
        for k, v in item.items():
            if isinstance(v, (list, dict)):
                row[k] = json.dumps(v, ensure_ascii=False)
            else:
                row[k] = v
        flat_data.append(row)

    fieldnames = list(flat_data[0].keys())
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat_data)

    logger.info("Saved CSV data to %s", filepath)
    return filepath


def scrape_localities_and_municipalities(output_dir: Path = DEFAULT_OUTPUT_DIR) -> Dict[str, Any]:
    """
    Main pipeline function to scrape dataset, clean localities, aggregate municipalities, and export files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fetch Package Metadata & Latest Resource
    pkg_metadata = fetch_dataset_metadata()
    resources = pkg_metadata.get("resources", [])
    latest_res = select_latest_resource(resources)

    # 2. Download Raw File if URL is available
    raw_url = latest_res.get("url")
    if raw_url:
        ext = Path(raw_url).suffix or ".xlsx"
        raw_file_path = output_dir / f"bycode_latest{ext}"
        download_raw_file(raw_url, raw_file_path)

    # 3. Scrape Records via Datastore API
    resource_id = latest_res.get("id")
    if not resource_id:
        raise ValueError("Selected resource has no ID for Datastore API query.")

    raw_records = scrape_datastore_records(resource_id)
    
    # 4. Clean Localities
    localities = [clean_locality_record(r) for r in raw_records]
    
    # 5. Aggregate Municipalities
    municipalities = aggregate_municipalities(localities)

    # 6. Save Data Files
    loc_json = save_json(localities, output_dir / "localities.json")
    loc_csv = save_csv(localities, output_dir / "localities.csv")
    
    muni_json = save_json(municipalities, output_dir / "municipalities.json")
    muni_csv = save_csv(municipalities, output_dir / "municipalities.csv")

    summary = {
        "resource_name": latest_res.get("name"),
        "resource_id": resource_id,
        "total_localities": len(localities),
        "total_municipalities": len(municipalities),
        "files_saved": [
            str(loc_json),
            str(loc_csv),
            str(muni_json),
            str(muni_csv),
        ]
    }
    
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Scrape local municipalities and localities in Israel from data.gov.il"
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to save output files (default: {DEFAULT_OUTPUT_DIR})"
    )

    args = parser.parse_args()

    try:
        summary = scrape_localities_and_municipalities(args.output_dir)
        print("\n=== Scraping Complete ===")
        print(f"Resource Name:        {summary['resource_name']}")
        print(f"Total Localities:     {summary['total_localities']}")
        print(f"Total Municipalities: {summary['total_municipalities']}")
        print("Output Files:")
        for path in summary["files_saved"]:
            print(f" - {path}")
    except Exception as e:
        logger.error("Failed to scrape dataset: %s", e, exc_info=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
