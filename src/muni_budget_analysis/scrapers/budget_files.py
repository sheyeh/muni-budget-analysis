#!/usr/bin/env python3
"""
budget_files.py

Scraper to discover, prioritize, download, and convert municipal budget files for all local municipalities in Israel.

Config File Support:
- Loads inclusions and exclusions dynamically from config/budget_keywords.json.

Strict Scope Enforcement & Multi-Level Crawling:
- Collects files representing actual municipal budgets (תקציב, ספר תקציב, תקציב רגיל, תקציב מותאם, תבר, הצעת תקציב).
- Excludes non-budget items (food vouchers, kindergartens, environmental units, traffic, salary, signed audit reports, development budgets, etc.).
- Performs multi-level sub-page crawling to follow annual budget links and extract embedded files.
- Unquotes all percent-encoded URLs and paths for clean CSV/JSON output.

Format Hierarchy (per Municipality and Year):
1. Priority 1: Excel Files (.xlsx, .xls, .csv)
2. Priority 2: PDF Files (.pdf) [Selected only if no Excel file exists for that year]
3. Priority 3: FlipHTML5 Publications [Selected only if neither Excel nor PDF exists for that year; converted to PDF]

Outputs:
- Downloaded files under: data/budgets/<muni_code>_<muni_name>/<year>/
- data/budgets/budget_files.json
- data/budgets/budget_files.csv
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
from typing import Any, Dict, List, Optional, Tuple, Set

# Ensure 'src' is in sys.path when running script directly
SRC_DIR = Path(__file__).resolve().parents[2]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    import img2pdf
except ImportError:
    img2pdf = None

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_FILE = PROJECT_ROOT / "data" / "localities" / "municipality_websites.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "budgets"
CONFIG_FILE_PATH = Path(__file__).resolve().parent.parent / "config" / "budget_keywords.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) MuniBudgetAnalysis/1.0"
}


def load_keyword_config(config_path: Optional[Path] = None) -> Tuple[List[str], List[str]]:
    """
    Load inclusion and exclusion keywords from an external JSON config file.
    """
    target_config = config_path or CONFIG_FILE_PATH

    if target_config.exists():
        try:
            with open(target_config, "r", encoding="utf-8") as f:
                data = json.load(f)
                inclusions = data.get("inclusions", [])
                exclusions = data.get("exclusions", [])
                logger.info("Loaded %d inclusions and %d exclusions from config: %s", len(inclusions), len(exclusions), target_config)
                return inclusions, exclusions
        except Exception as e:
            logger.error("Failed to load keyword config from %s: %s", target_config, e)
            return [], []

    logger.error("Keyword config file not found: %s", target_config)
    return [], []


STRICT_BUDGET_INCLUSIONS, STRICT_EXCLUSIONS = load_keyword_config()
EXCLUDED_EXTENSIONS = [".jpg", ".png", ".gif", ".mp4", ".zip", ".doc", ".docx"]


def extract_years_from_text(text: str) -> List[int]:
    """Extract 4-digit years (1990-2026) from text or URL."""
    if not text:
        return []
    text_unquoted = urllib.parse.unquote(text)
    matches = re.findall(r"(?:199\d|20[0-2]\d)", text_unquoted)
    years = sorted(list(set(int(y) for y in matches)), reverse=True)
    return years


def is_strict_budget_document(
    link_text: str,
    href_url: str,
    page_context: str = "",
    local_context: str = "",
) -> bool:
    """
    Returns True if the link/file represents an actual municipal budget document.

    page_context: page-wide signal (URL, title, main heading) - used only to help
    recognize budget-related generic link text (e.g. "click here"), never to
    exclude. Sitewide boilerplate (an accessibility statement heading, an FOI
    link elsewhere on the page) is common to every link on that page and would
    otherwise disqualify unrelated files just for sharing a page with it.
    local_context: tight, link-local signal (the immediate row/list-item/paragraph
    text) - specific enough to this one link to be used for both inclusion and
    exclusion.
    """
    text_clean = link_text.strip() if link_text else ""
    url_clean = urllib.parse.unquote(href_url) if href_url else ""
    page_ctx_clean = urllib.parse.unquote(page_context) if page_context else ""
    local_ctx_clean = urllib.parse.unquote(local_context) if local_context else ""

    combined_text = f"{text_clean} {page_ctx_clean} {local_ctx_clean} {url_clean}"

    # Link text or URL filename or context must contain a budget inclusion keyword
    has_budget_term = any(inc in combined_text for inc in STRICT_BUDGET_INCLUSIONS)

    # If link text is generic (e.g. 'לחץ כאן' or 'להורדה'), check if context has budget terms
    if not has_budget_term and (any(ext in url_clean.lower() for ext in [".pdf", ".xlsx", ".xls", ".csv"]) or "flip" in url_clean.lower()):
        if any(inc in page_ctx_clean or inc in local_ctx_clean for inc in STRICT_BUDGET_INCLUSIONS):
            has_budget_term = True

    if not has_budget_term:
        return False

    # Must NOT contain any exclusion keywords - deliberately excludes page_context here.
    matched_exclusions = [ex for ex in STRICT_EXCLUSIONS if ex in text_clean or ex in url_clean or ex in local_ctx_clean]
    if matched_exclusions:
        logger.info(
            "Excluding candidate '%s' (%s): matched exclusion keyword(s) %s",
            text_clean or url_clean, url_clean, matched_exclusions
        )
        return False

    return True


def get_matched_inclusion_keywords(*texts: str) -> List[str]:
    """Return the budget inclusion keywords found across the given text fragments (for logging)."""
    combined = " ".join(t for t in texts if t)
    return [inc for inc in STRICT_BUDGET_INCLUSIONS if inc in combined]


def determine_file_type(url: str, text: str) -> Optional[str]:
    """
    Classify link format into: 'excel', 'pdf', or 'fliphtml'.
    """
    if not url:
        return None
    url_lower = urllib.parse.unquote(url).lower()
    text_lower = text.lower() if text else ""

    if any(url_lower.endswith(ext) or f"{ext}?" in url_lower for ext in [".xlsx", ".xls", ".csv"]):
        return "excel"
    if "excel" in text_lower or "אקסל" in text_lower or "csv" in text_lower:
        return "excel"

    if url_lower.endswith(".pdf") or ".pdf?" in url_lower or "pdf" in text_lower:
        return "pdf"

    if "fliphtml5.com" in url_lower or "fliphtml" in url_lower or "flipbook" in url_lower:
        return "fliphtml"

    return None


def fetch_html_content(url: str, timeout: int = 6) -> Optional[str]:
    """Safely fetch HTML content from URL with path quote encoding and cookie handling."""
    import time
    time.sleep(0.3)
    try:
        parsed = urllib.parse.urlparse(url)
        clean_path = urllib.parse.quote(urllib.parse.unquote(parsed.path))
        safe_url = urllib.parse.urlunparse(parsed._replace(path=clean_path))

        import http.cookiejar
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        opener.addheaders = [('User-Agent', HEADERS['User-Agent'])]

        with opener.open(safe_url, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "html" in content_type.lower() or "text" in content_type.lower():
                return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        pass
    return None


def _same_site(netloc_a: str, netloc_b: str) -> bool:
    """Loose same-site check (ignores www./subdomains) for route-blocking decisions."""
    a = re.sub(r"^www\.", "", netloc_a.split(":")[0].lower())
    b = re.sub(r"^www\.", "", netloc_b.split(":")[0].lower())
    return bool(a) and bool(b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def fetch_rendered_html(url: str, timeout: int = 20) -> Optional[str]:
    """
    Render a page with a headless browser and return the fully rendered HTML.

    Used as a fallback for JavaScript-driven pages (e.g. Angular/SharePoint
    "transparency portal" widgets) where budget documents are populated client-side
    after page load and never appear in the plain HTTP response. Also clicks any
    tab/accordion/button-like controls to reveal content hidden behind them
    (e.g. per-year budget accordions).
    """
    if sync_playwright is None:
        return None

    def goto_resilient(page, target_url: str) -> None:
        """Navigate, tolerating pages that never reach "networkidle" (persistent
        background polling - chat widgets, analytics beacons - is common on
        municipal sites and would otherwise time this out every time). Falls back
        to a much looser "load" wait, which just needs the initial page to finish
        loading, not for background traffic to fully quiet down."""
        try:
            page.goto(target_url, timeout=timeout * 1000, wait_until="networkidle")
        except Exception:
            page.goto(target_url, timeout=timeout * 1000, wait_until="load")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                # Route-block at the browser-context level (not just per-page) so it also
                # covers any popup a click opens - a popup is a brand new page object that
                # a per-page route handler would never see.
                context = browser.new_context(user_agent=HEADERS["User-Agent"])
                target_netloc = urllib.parse.urlparse(url).netloc

                def block_offsite_navigation(route):
                    # Some clicked controls turn out to be social-share widgets (target="_blank"
                    # links to twitter.com/facebook.com/etc., built dynamically from the page's
                    # own title/URL via JS rather than a static href we could filter out
                    # beforehand). Abort any full-page/popup navigation to a different site
                    # before the browser ever sends the request - reacting after the fact
                    # (closing the popup, navigating back) is too late to stop the connection
                    # itself from being made.
                    request = route.request
                    if request.resource_type == "document" and not _same_site(
                        urllib.parse.urlparse(request.url).netloc, target_netloc
                    ):
                        route.abort()
                    else:
                        route.continue_()

                context.route("**/*", block_offsite_navigation)
                page = context.new_page()
                page.on("popup", lambda popup: popup.close())
                goto_resilient(page, url)
                original_origin = urllib.parse.urlparse(page.url).netloc

                def ensure_on_page() -> bool:
                    """Navigate back if a click (or a delayed script) sent us off-page.
                    Returns False if recovery itself fails, so the caller can bail out."""
                    if urllib.parse.urlparse(page.url).netloc == original_origin:
                        return True
                    try:
                        goto_resilient(page, url)
                        return True
                    except Exception:
                        return False

                toggles = page.query_selector_all(
                    "[role='tab'], [ng-click], .accordion-toggle, .accordion-header, "
                    ".collapse-toggle, button"
                )
                for toggle in toggles[:60]:
                    try:
                        toggle.click(timeout=1000)
                        page.wait_for_timeout(200)
                    except Exception:
                        continue
                    # A click - or a delayed script it triggers - may still navigate the
                    # main page itself (not just open a popup), e.g. via location.href.
                    # Recover immediately so later clicks - and the final content()
                    # capture - stay on the intended page.
                    if not ensure_on_page():
                        break

                page.wait_for_timeout(1000)
                ensure_on_page()
                return page.content()
            finally:
                # Close the browser here, before the `with sync_playwright()` block
                # exits and tears down the driver connection underneath it.
                browser.close()
    except Exception as e:
        logger.warning("Headless render failed for %s: %s", url, e)
        return None


def _extract_fliphtml_page_images_via_browser(clean_url: str, timeout: int = 30) -> Dict[int, str]:
    """
    Render a FlipHTML5 publication and collect each page's full-resolution image URL.

    FlipHTML5's per-page images are never present as static links (only the cover
    thumbnail `files/shot.jpg` is), and the reader's own page manifest is a
    proprietary-obfuscated blob inside `javascript/config.js` - not something we can
    regex-parse. The reader does, however, expose a "thumbnail preview" panel whose
    items already exist in the DOM (though hidden until toggled) with an
    `aria-label="page N"` per page. Clicking each one triggers the reader to fetch
    that page's real `files/large/<hash>.<ext>` image, which we capture via response
    interception - keyed by page number, since the hashed filenames carry no
    order/sequence info of their own.
    """
    page_images: Dict[int, str] = {}
    if sync_playwright is None:
        return page_images

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                current_click_matches: List[str] = []

                def on_response(resp):
                    if re.search(r"files/large/[^?]*\.(?:jpe?g|png|webp)", resp.url, re.I):
                        current_click_matches.append(resp.url)

                page.on("response", on_response)
                page.goto(clean_url + "/", timeout=timeout * 1000, wait_until="load")
                page.wait_for_timeout(2000)

                # Toggle the thumbnail-preview panel open - its items are hidden until
                # this is clicked, regardless of the reader's UI language/theme, so we
                # match on the Hebrew label already seen in the wild as well as the
                # generic "thumbnail" substring.
                thumb_btn = page.query_selector(
                    "[aria-label*='ממוזערות'], [aria-label*='thumbnail' i]"
                )
                if thumb_btn:
                    try:
                        thumb_btn.click(timeout=3000)
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass

                def click_pass(wait_ms: int) -> int:
                    """One pass over every thumbnail item still missing from
                    page_images. Re-queries elements fresh each pass, since the
                    swiper appears to virtualize/recycle its DOM nodes as it
                    scrolls, making stale element handles from an earlier pass
                    unreliable. Returns how many items were still missing going in."""
                    items = page.query_selector_all(".thumbnailSwiper .item")
                    missing_count = 0
                    for item in items:
                        aria = item.get_attribute("aria-label") or ""
                        page_num_match = re.search(r"(\d+)", aria)
                        if not page_num_match:
                            continue
                        page_num = int(page_num_match.group(1))
                        if page_num in page_images:
                            continue
                        missing_count += 1

                        current_click_matches.clear()
                        try:
                            item.scroll_into_view_if_needed(timeout=1500)
                            page.wait_for_timeout(60)
                            item.click(timeout=1500)
                        except Exception:
                            continue
                        page.wait_for_timeout(wait_ms)

                        if current_click_matches:
                            page_images[page_num] = current_click_matches[-1]
                    return missing_count

                total_items = len(page.query_selector_all(".thumbnailSwiper .item"))
                click_pass(300)
                # A couple of retry passes for whatever the swiper's DOM virtualization
                # or click-timing caused to be missed on the first sweep - re-querying
                # fresh elements and waiting a bit longer tends to pick up the rest.
                for _ in range(2):
                    if len(page_images) >= total_items:
                        break
                    click_pass(500)

                page.wait_for_timeout(1500)

                if total_items and len(page_images) < total_items:
                    logger.warning(
                        "FlipHTML thumbnail capture incomplete for %s: got %d of %d expected pages",
                        clean_url, len(page_images), total_items
                    )
            finally:
                browser.close()
    except Exception as e:
        logger.warning("FlipHTML browser-based page extraction failed for %s: %s", clean_url, e)

    return page_images


def convert_fliphtml_to_pdf(flip_url: str, save_path: Path) -> bool:
    """
    Convert a FlipHTML5 publication link to a PDF document.
    Attempts, in order:
    1. Direct PDF download link (`files/download/<name>.pdf`).
    2. Rendering the reader with a headless browser and clicking through its
       thumbnail-preview panel to collect every page's real image (see
       `_extract_fliphtml_page_images_via_browser`).
    3. Last resort: whatever page image references happen to be in the static HTML -
       in practice this is only ever the cover thumbnail (`files/shot.jpg`), since
       FlipHTML5 loads every other page's image dynamically via JS.
    """
    clean_url = urllib.parse.urldefrag(flip_url)[0].split("?")[0].rstrip("/")
    if "index.html" in clean_url:
        clean_url = clean_url.rsplit("/", 1)[0]

    # 1. Check direct PDF download link
    match = re.search(r"fliphtml5\.com/([^/]+)/([^/\?#]+)", clean_url)
    if match:
        user_id, book_id = match.group(1), match.group(2)
        direct_pdf_url = f"https://online.fliphtml5.com/{user_id}/{book_id}/files/download/{book_id}.pdf"
        try:
            req = urllib.request.Request(direct_pdf_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(save_path, "wb") as f:
                        f.write(resp.read())
                    logger.info("Directly downloaded FlipHTML PDF from %s", direct_pdf_url)
                    return True
        except Exception:
            pass

    if img2pdf is None:
        logger.warning("img2pdf library not available for FlipHTML image-to-PDF conversion.")
        return False

    # 2. Render with a headless browser and capture every page's real image
    img_urls_ordered: List[str] = []
    page_images = _extract_fliphtml_page_images_via_browser(clean_url)
    if page_images:
        img_urls_ordered = [page_images[n] for n in sorted(page_images)]

    # 3. Last resort: whatever's in the static HTML (in practice just the cover,
    # since FlipHTML5 loads every other page's image dynamically via JS)
    if not img_urls_ordered:
        if BeautifulSoup is None:
            return False
        try:
            req = urllib.request.Request(clean_url + "/", headers=HEADERS)
            with urllib.request.urlopen(req, timeout=6) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                soup = BeautifulSoup(html, "html.parser")
                img_rel_paths: Set[str] = set()
                for tag in soup.find_all(["img", "a"]):
                    for attr in ("src", "href", "data-src"):
                        val = tag.get(attr)
                        if val and re.search(r"files/(?:large|shot)[^\s\"'?]*\.(?:webp|jpg|jpeg|png)", val, re.I):
                            img_rel_paths.add(val.split("?")[0].lstrip("/"))
                if not img_rel_paths:
                    img_rel_paths = {"files/shot.jpg"}
                img_urls_ordered = sorted(f"{clean_url}/{rel}" for rel in img_rel_paths)
        except Exception as e:
            logger.warning("FlipHTML static-HTML fallback failed for %s: %s", flip_url, e)

    if not img_urls_ordered:
        return False

    images: List[bytes] = []
    for img_url in img_urls_ordered:
        try:
            ireq = urllib.request.Request(img_url, headers=HEADERS)
            with urllib.request.urlopen(ireq, timeout=8) as iresp:
                if iresp.status == 200:
                    images.append(iresp.read())
        except Exception:
            pass

    if images:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(img2pdf.convert(images))
        logger.info("Compiled %d FlipHTML page images into PDF: %s", len(images), save_path)
        return True

    return False


def scan_page_for_budget_candidates(
    page_html: str,
    page_url: str,
    site_url: str,
    muni_code: Any,
    raw_name: str,
    muni_type: Any,
) -> List[Dict[str, Any]]:
    """
    Extract strict-budget document link candidates from a single (already-fetched)
    page's HTML. Shared by both the plain HTTP fetch path and the headless-browser
    render fallback, since both hand off an HTML string to scan identically.
    """
    candidates: List[Dict[str, Any]] = []

    psoup = BeautifulSoup(page_html, "html.parser")
    page_title = psoup.title.get_text(strip=True) if psoup.title else ""
    # Only the page's main heading (first h1, falling back to first h2) - joining
    # every h1/h2 on the page pulls in unrelated sitewide headings (e.g. footer
    # accessibility widgets) that then get applied to every link on the page.
    main_heading = psoup.find("h1") or psoup.find("h2")
    h1_text = main_heading.get_text(strip=True) if main_heading else ""
    page_context = f"{page_url} {page_title} {h1_text}"

    for a in psoup.find_all(["a", "iframe", "embed"]):
        href = a.get("href") or a.get("src", "")
        if not href:
            continue

        text = a.get_text(strip=True) if a.name == "a" else ""
        raw_join = urllib.parse.urljoin(page_url, href)

        # Fix relative upload paths (e.g. /תקציבים/uploads/n/... -> /uploads/n/...)
        if "uploads/n/" in raw_join:
            rel_part = raw_join.split("uploads/n/")[-1]
            full_url = f"{site_url}/uploads/n/{rel_part}"
        else:
            full_url = raw_join

        # Prefer the tightest scoped ancestor (single row/list item/paragraph).
        # Only fall back to a "div" ancestor if it's a small, scoped container -
        # a large wrapping div can hold unrelated sitewide links/text (e.g. an
        # accessibility widget) that would otherwise leak into every link's context.
        parent = a.find_parent(["tr", "li", "p"])
        if not parent:
            div_parent = a.find_parent("div")
            if div_parent and len(div_parent.find_all("a")) <= 5:
                parent = div_parent
        parent_text = parent.get_text(" ", strip=True) if parent else ""

        if not is_strict_budget_document(text, full_url, page_context=page_context, local_context=parent_text):
            continue

        ftype = determine_file_type(full_url, text)
        if not ftype:
            continue

        years = extract_years_from_text(text) or extract_years_from_text(parent_text) or extract_years_from_text(full_url) or extract_years_from_text(page_context)
        year = years[0] if years else 0

        # Rank candidate score (budget books > work plans / quarterly)
        score = 10
        if "תקציב המועצה" in text or "ספר תקציב" in text:
            score = 100
        elif "תקציב" in text:
            score = 50

        candidates.append({
            "municipality_code": muni_code,
            "municipality_name": raw_name,
            "municipality_type": muni_type,
            "website_url": site_url,
            "budget_year": year,
            "file_type": ftype,
            "source_url": urllib.parse.unquote(full_url),
            "link_text": urllib.parse.unquote(text or Path(urllib.parse.urlparse(full_url).path).name),
            "score": score
        })

    return candidates


def discover_municipality_budget_files(muni: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Scrape budget file candidates for a single municipality, enforcing strict budget criteria and multi-level sub-page crawling.
    """
    site_url = muni.get("website_url")
    if not site_url:
        return []

    raw_name = muni.get("municipality_name")
    muni_code = muni.get("municipality_code")

    logger.info("Scanning budget files for %s (%s)...", raw_name, site_url)

    main_html = fetch_html_content(site_url)
    if not main_html or BeautifulSoup is None:
        return []

    soup = BeautifulSoup(main_html, "html.parser")
    budget_page_urls: Set[str] = set()

    # Step 1: Discover Level-1 budget sub-pages
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"]
        if is_strict_budget_document(text, href) or any(kw in text for kw in ["תקציב", "ספר תקציב", "חוברת תקציב", "גזברות"]):
            full_url = urllib.parse.urljoin(site_url, href)
            if full_url.startswith("http"):
                budget_page_urls.add(full_url)

    budget_page_urls.add(site_url)
    ordered_urls = sorted(list(budget_page_urls), key=lambda u: 0 if "תקציב" in urllib.parse.unquote(u) else 1)

    # Step 2: Level-2 sub-page crawling (follow year-specific sub-pages like /תקציב-לשנת-הכספים-2021/)
    additional_pages: Set[str] = set()
    for page_url in ordered_urls[:15]:
        page_html = fetch_html_content(page_url) if page_url != site_url else main_html
        if not page_html:
            continue
        # A bare year link (e.g. "2021") is only trustworthy as an annual budget
        # sub-link when the *current* page is itself already budget-related - on the
        # homepage or other generic pages, a bare year matches unrelated content
        # (e.g. a "Strategic Plan 2026" page) and pulls it into the crawl scope.
        page_is_budget_related = "תקציב" in urllib.parse.unquote(page_url)
        psoup = BeautifulSoup(page_html, "html.parser")
        for a in psoup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            has_budget_term = "תקציב" in text or "תקציב" in href
            has_bare_year = any(yr in text or yr in href for yr in ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019"])
            if has_budget_term or (page_is_budget_related and has_bare_year):
                if not any(ext in href.lower() for ext in [".pdf", ".xlsx", ".xls", ".csv"]):
                    full_url = urllib.parse.urljoin(page_url, href)
                    if full_url.startswith("http"):
                        additional_pages.add(full_url)

    budget_page_urls.update(additional_pages)

    # Prioritize sub-pages containing תקציב in path/URL
    sorted_pages = sorted(list(budget_page_urls), key=lambda u: 0 if "תקציב" in urllib.parse.unquote(u) else 1)

    # Step 3: Collect document links matching strict budget criteria
    raw_candidates: List[Dict[str, Any]] = []
    muni_type = muni.get("municipality_type")

    for page_url in sorted_pages[:20]:
        page_html = fetch_html_content(page_url) if page_url != site_url else main_html
        if not page_html:
            continue
        raw_candidates.extend(
            scan_page_for_budget_candidates(page_html, page_url, site_url, muni_code, raw_name, muni_type)
        )

    # Step 3b: Headless-browser fallback for JavaScript-rendered pages (e.g. Angular /
    # SharePoint "transparency portal" widgets) where budget documents are populated
    # client-side and never appear in the plain HTTP response, so Step 3 finds nothing.
    if not raw_candidates:
        if sync_playwright is None:
            logger.warning(
                "No budget files found via static HTML for %s, and Playwright is not installed "
                "so the headless-render fallback is unavailable (this page may be JavaScript-rendered, "
                "e.g. an Angular/SharePoint portal). Install it with: "
                "pip install playwright && playwright install chromium",
                raw_name
            )
        else:
            logger.info(
                "No budget files found via static HTML for %s; retrying top page(s) with headless browser rendering.",
                raw_name
            )
            for page_url in sorted_pages[:3]:
                rendered_html = fetch_rendered_html(page_url)
                if not rendered_html:
                    continue
                rendered_candidates = scan_page_for_budget_candidates(
                    rendered_html, page_url, site_url, muni_code, raw_name, muni_type
                )
                if rendered_candidates:
                    logger.info(
                        "Headless rendering recovered %d budget file candidate(s) for %s from %s",
                        len(rendered_candidates), raw_name, page_url
                    )
                raw_candidates.extend(rendered_candidates)

    # De-duplicate by source URL - the headless-render fallback can click the same
    # accordion/tab open more than once, adding identical candidates repeatedly.
    seen_urls: Set[str] = set()
    deduped_candidates: List[Dict[str, Any]] = []
    for cand in raw_candidates:
        if cand["source_url"] not in seen_urls:
            seen_urls.add(cand["source_url"])
            deduped_candidates.append(cand)
    raw_candidates = deduped_candidates

    # Step 4: Group candidates by year and enforce format priority (Excel > PDF > FlipHTML) and score
    candidates_by_year: Dict[int, List[Dict[str, Any]]] = {}
    for cand in raw_candidates:
        yr = cand["budget_year"]
        candidates_by_year.setdefault(yr, []).append(cand)

    selected_files: List[Dict[str, Any]] = []

    for yr, cands in candidates_by_year.items():
        # Sort candidates by score descending
        cands_sorted = sorted(cands, key=lambda c: c.get("score", 0), reverse=True)

        non_regular = [c for c in cands_sorted if "בלתי רגיל" in c["link_text"]]
        regular = [c for c in cands_sorted if "רגיל" in c["link_text"] and "בלתי רגיל" not in c["link_text"]]

        if regular or non_regular:
            # This municipality distinguishes regular ("רגיל") budget documents from
            # non-regular/supplementary ones ("בלתי רגיל") - e.g. Tel Aviv publishes
            # both under one year's accordion. Keep only the regular ones. Unlike the
            # single-file-per-year default below, keep every distinct regular document
            # (a detail book, a summary spreadsheet, explanatory notes, etc. are
            # different documents, not format variants of the same file) - but still
            # prefer Excel over PDF/FlipHTML whenever the same titled document exists
            # in more than one format.
            by_title: Dict[str, List[Dict[str, Any]]] = {}
            for c in regular:
                by_title.setdefault(c["link_text"], []).append(c)
            for title, group in by_title.items():
                excels = [c for c in group if c["file_type"] == "excel"]
                pdfs = [c for c in group if c["file_type"] == "pdf"]
                flips = [c for c in group if c["file_type"] == "fliphtml"]
                if excels:
                    selected_files.append(excels[0])
                elif pdfs:
                    selected_files.append(pdfs[0])
                elif flips:
                    selected_files.append(flips[0])
            continue

        # Default: no regular/non-regular distinction found - single best file per year.
        excels = [c for c in cands_sorted if c["file_type"] == "excel"]
        pdfs = [c for c in cands_sorted if c["file_type"] == "pdf"]
        flips = [c for c in cands_sorted if c["file_type"] == "fliphtml"]

        if excels:
            selected_files.append(excels[0])
        elif pdfs:
            selected_files.append(pdfs[0])
        elif flips:
            selected_files.append(flips[0])

    return selected_files


def download_budget_file(
    item: Dict[str, Any],
    output_dir: Path
) -> Dict[str, Any]:
    """
    Download or convert a single selected budget file.
    """
    muni_code = item["municipality_code"]
    muni_name = re.sub(r"[^\w\s-]", "", item["municipality_name"]).strip().replace(" ", "_")
    year_str = str(item["budget_year"]) if item["budget_year"] > 0 else "general"
    
    target_dir = output_dir / f"{muni_code}_{muni_name}" / year_str
    target_dir.mkdir(parents=True, exist_ok=True)

    src_url = item["source_url"]
    ftype = item["file_type"]

    filename = Path(urllib.parse.urlparse(src_url).path).name
    filename = urllib.parse.unquote(filename)
    # Re-derive the basename post-unquote: percent-encoded separators (e.g. "..%2F")
    # only become traversal sequences after decoding, so this strips any directory
    # components (including "..") introduced by the decode.
    filename = Path(filename).name
    if not filename or filename in (".", "..") or len(filename) < 3:
        filename = f"budget_{year_str}.{'xlsx' if ftype == 'excel' else 'pdf'}"

    save_path = (target_dir / filename).resolve()
    if not save_path.is_relative_to(target_dir.resolve()):
        # Defense in depth: refuse to write anywhere outside the target directory.
        filename = f"budget_{year_str}.{'xlsx' if ftype == 'excel' else 'pdf'}"
        save_path = (target_dir / filename).resolve()

    res_item = dict(item)
    res_item["downloaded_path"] = str(save_path.relative_to(PROJECT_ROOT)) if save_path.exists() else None
    res_item["download_success"] = False
    res_item["file_size_bytes"] = 0

    matched_keywords = get_matched_inclusion_keywords(item.get("link_text", ""), src_url)
    logger.info(
        "Downloading %s file for %s (%s), year %s: matched keyword(s) %s, score=%d, link_text='%s', url=%s",
        ftype, item["municipality_name"], muni_code, year_str,
        matched_keywords or ["<page context match>"], item.get("score", 0),
        item.get("link_text", ""), src_url
    )

    try:
        parsed = urllib.parse.urlparse(src_url)
        clean_path = urllib.parse.quote(urllib.parse.unquote(parsed.path))
        safe_url = urllib.parse.urlunparse(parsed._replace(path=clean_path))

        if ftype == "fliphtml":
            save_pdf_path = save_path.with_suffix(".pdf")
            success = convert_fliphtml_to_pdf(src_url, save_pdf_path)
            if success and save_pdf_path.exists():
                res_item["downloaded_path"] = str(save_pdf_path.relative_to(PROJECT_ROOT))
                res_item["download_success"] = True
                res_item["file_size_bytes"] = save_pdf_path.stat().st_size
                res_item["file_type"] = "fliphtml_pdf"
        else:
            import http.cookiejar
            cj = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            opener.addheaders = [('User-Agent', HEADERS['User-Agent'])]

            with opener.open(safe_url, timeout=10) as resp:
                content = resp.read()
                with open(save_path, "wb") as f:
                    f.write(content)
                res_item["downloaded_path"] = str(save_path.relative_to(PROJECT_ROOT))
                res_item["download_success"] = True
                res_item["file_size_bytes"] = len(content)
    except Exception as e:
        logger.warning("Download failed for %s (%s): %s", item["municipality_name"], src_url, e)

    return res_item


def scrape_all_budget_files(
    municipalities: List[Dict[str, Any]],
    output_dir: Path,
    max_workers: int = 10,
    download_files: bool = True
) -> List[Dict[str, Any]]:
    """
    Scrape and download budget files for all municipalities concurrently.
    """
    logger.info("Discovering budget files for %d municipalities...", len(municipalities))

    all_selected: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(discover_municipality_budget_files, m): m for m in municipalities}
        for future in as_completed(futures):
            try:
                res = future.result()
                all_selected.extend(res)
            except Exception as e:
                m = futures[future]
                logger.error("Error scanning %s: %s", m.get("municipality_name"), e)

    logger.info("Discovered %d strict budget files matching format priorities.", len(all_selected))

    if not download_files:
        return all_selected

    logger.info("Downloading discovered budget files...")
    final_records: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_budget_file, item, output_dir): item for item in all_selected}
        for future in as_completed(futures):
            try:
                res = future.result()
                final_records.append(res)
            except Exception as e:
                item = futures[future]
                logger.error("Error downloading file for %s: %s", item.get("municipality_name"), e)

    return final_records


def save_budget_summary_json(data: List[Dict[str, Any]], filepath: Path) -> Path:
    """Save budget files summary to JSON with unquoted URLs."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Saved budget summary JSON to %s", filepath)
    return filepath


def save_budget_summary_csv(data: List[Dict[str, Any]], filepath: Path) -> Path:
    """Save budget files summary to CSV with unquoted URLs."""
    if not data:
        return filepath
    filepath.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "municipality_code", "municipality_name", "municipality_type",
        "website_url", "budget_year", "file_type", "download_success",
        "downloaded_path", "file_size_bytes", "source_url", "link_text"
    ]

    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in data:
            row_copy = dict(row)
            if row_copy.get("source_url"):
                row_copy["source_url"] = urllib.parse.unquote(row_copy["source_url"])
            if row_copy.get("downloaded_path"):
                row_copy["downloaded_path"] = urllib.parse.unquote(row_copy["downloaded_path"])
            if row_copy.get("link_text"):
                row_copy["link_text"] = urllib.parse.unquote(row_copy["link_text"])
            writer.writerow(row_copy)

    logger.info("Saved budget summary CSV to %s", filepath)
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Scrape and download budget files (Excel > PDF > FlipHTML) for all Israeli municipalities"
    )
    parser.add_argument(
        "-i", "--input",
        type=Path,
        default=DEFAULT_INPUT_FILE,
        help="Input municipality_websites.json path"
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to save downloaded budget files and metadata"
    )
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=CONFIG_FILE_PATH,
        help="Path to external budget_keywords.json config file"
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=10,
        help="Number of concurrent worker threads (default: 10)"
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Only discover links without downloading files"
    )
    parser.add_argument(
        "--municipality-code",
        type=int,
        default=None,
        help="Restrict the run to a single municipality by its exact municipality_code"
    )
    parser.add_argument(
        "--municipality-name",
        type=str,
        default=None,
        help="Restrict the run to municipalities whose name contains this substring"
    )

    args = parser.parse_args()

    if not args.input.exists():
        logger.error("Input file %s does not exist. Run website scraper first.", args.input)
        raise SystemExit(1)

    # Reload keywords if custom config path provided
    global STRICT_BUDGET_INCLUSIONS, STRICT_EXCLUSIONS
    STRICT_BUDGET_INCLUSIONS, STRICT_EXCLUSIONS = load_keyword_config(args.config)

    with open(args.input, "r", encoding="utf-8") as f:
        municipalities = json.load(f)

    valid_munis = [m for m in municipalities if m.get("website_url")]

    if args.municipality_code is not None:
        valid_munis = [m for m in valid_munis if m.get("municipality_code") == args.municipality_code]
    if args.municipality_name:
        valid_munis = [m for m in valid_munis if args.municipality_name in (m.get("municipality_name") or "")]

    if not valid_munis:
        logger.error(
            "No municipality matched the given filter (--municipality-code=%s, --municipality-name=%s).",
            args.municipality_code, args.municipality_name
        )
        raise SystemExit(1)

    records = scrape_all_budget_files(
        valid_munis,
        output_dir=args.output_dir,
        max_workers=args.workers,
        download_files=not args.no_download
    )

    json_path = save_budget_summary_json(records, args.output_dir / "budget_files.json")
    csv_path = save_budget_summary_csv(records, args.output_dir / "budget_files.csv")

    print("\n=== Strict Budget File Scraping Complete ===")
    print(f"Total Budget Files Discovered: {len(records)}")
    excels = len([r for r in records if r.get("file_type") == "excel"])
    pdfs = len([r for r in records if r.get("file_type") in ["pdf", "fliphtml_pdf"]])
    print(f" - Excel Files: {excels}")
    print(f" - PDF Files:   {pdfs}")
    print(f"JSON Summary: {json_path}")
    print(f"CSV Summary:  {csv_path}")


if __name__ == "__main__":
    main()
