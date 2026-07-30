"""
Scrapers module for fetching data from Israeli government open data portals (e.g. data.gov.il).
"""

from .localities import scrape_localities_and_municipalities
from .municipality_websites import scrape_all_municipality_websites, resolve_municipality_website

__all__ = [
    "scrape_localities_and_municipalities",
    "scrape_all_municipality_websites",
    "resolve_municipality_website",
]
