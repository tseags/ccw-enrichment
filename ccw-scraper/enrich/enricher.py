"""
Crawl CCW vendor websites and enrich records via the Claude API.

Concurrency model
─────────────────
• asyncio event loop drives everything.
• A global semaphore (max 3) caps total in‑flight HTTP requests.
• Per‑domain locks + 2‑second sleeps enforce politeness.
• Actual HTTP is sync `requests` wrapped in run_in_executor so the
  event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import random
import re
import struct
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import anthropic
import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────

USER_AGENT = "CCWDirectory/1.0 (training directory; contact@ccwdirectory.com)"
REQUEST_TIMEOUT = 15
MAX_RETRIES = 2
DOMAIN_DELAY = 2.0
GLOBAL_CONCURRENCY = 3
CLAUDE_CONCURRENCY = 2  # caps parallel Claude calls (TPM limits on long page text)
CLAUDE_MAX_RETRIES = 4
CLAUDE_RETRY_BASE_SECONDS = 2.0
MAX_EXTRA_PAGES = 2
TEXT_CHAR_LIMIT = 20_000
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
CLAUDE_MAX_TOKENS = 1000

LINK_KEYWORDS = re.compile(
    r"price|course|class|training|ccw|cost|fee|schedul", re.IGNORECASE
)

FALLBACK_PATHS = ["/about", "/courses"]

OUTPUT_COLUMNS = [
    "county", "needs_review", "vendor_name", "instructor_names", "email", "phone",
    "website_url", "booking_capability", "city", "state", "address",
    "price_16hr_day1", "price_16hr_day2", "price_16hr_full",
    "price_8hr_renewal", "price_8hr_initial", "price_add_a_gun",
    "vendor_description", "crawl_status", "enrichment_confidence",
    "confidence_notes", "logo_path", "instructor_image_paths",
    "training_image_paths", "enriched_at",
]

ENRICHMENT_FIELDS = [
    "booking_capability", "address",
    "price_16hr_day1", "price_16hr_day2", "price_16hr_full",
    "price_8hr_renewal", "price_8hr_initial", "price_add_a_gun",
    "vendor_description", "enrichment_confidence", "confidence_notes",
]

SYSTEM_PROMPT = """You are extracting structured data from a CCW firearms training vendor website. Return ONLY a valid JSON object with these exact fields. Return null for any field you cannot find with confidence.

{
  "booking_capability": "direct_booking" | "inquiry_only" | "unclear" | "none",
  "address": "full street address if found, null if not",
  "price_16hr_day1": "integer dollar amount only for Day 1 of 16hr initial course, null if not found",
  "price_16hr_day2": "integer dollar amount only for Day 2 of 16hr initial course, null if not found",
  "price_16hr_full": "integer dollar amount for full 16hr initial course (both days combined), null if not found",
  "price_8hr_renewal": "integer dollar amount for 8hr renewal course, null if not found",
  "price_8hr_initial": "integer dollar amount for 8hr initial course if offered, null if not found",
  "price_add_a_gun": "integer dollar amount to add an additional firearm to the permit, null if not found",
  "vendor_description": "2-4 sentence description of this vendor written in third person for a directory listing. Extract from their actual website copy — do not invent. Capture who they are, what they offer, and any notable differentiators. Null if nothing substantive found.",
  "enrichment_confidence": "high" | "medium" | "low",
  "confidence_notes": "brief explanation of what was unclear or missing"
}

Confidence scoring:
- "high" = found clear, specific data for most fields (pricing, booking, description)
- "medium" = some fields found but ambiguous or incomplete
- "low" = very little usable data extracted

Important pricing notes:
- Only return integer dollar amounts, no $ signs or cents
- If you see a range like $150-$200, return the lower number
- Day 1 and Day 2 prices are separate line items — only populate price_16hr_full if the vendor sells the full course as one purchase
- price_8hr_initial is rare — only populate if vendor explicitly offers an 8hr initial (not renewal) course"""


# ── image filtering constants ────────────────────────────────────────────────

STOCK_CDN_PATTERNS = re.compile(
    r"unsplash|shutterstock|istockphoto|istock|pexels|depositphotos"
    r"|adobestock|adobe\.stock|gettyimages|getty|pixabay",
    re.IGNORECASE,
)

GENERIC_FILENAME_PATTERNS = re.compile(
    r"stock|placeholder|banner-bg|shutterstock|istock|getty",
    re.IGNORECASE,
)

SKIP_EXTENSIONS = {".svg", ".gif"}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}

MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2 MB
MIN_IMAGE_DIM = 100  # px

MAX_LOGO = 1
MAX_INSTRUCTOR = 3
MAX_TRAINING = 3


# ── helpers ──────────────────────────────────────────────────────────────────

def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _vendor_slug(url: str) -> str:
    return _domain(url).replace("www.", "").replace(".", "-")


def _is_usable_http_url(url: str) -> bool:
    """True if URL can be fetched (http/https, non-empty host, no whitespace in host)."""
    u = url.strip()
    if not u:
        return False
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.netloc.split("@")[-1].split(":")[0]
    if not host or any(c in host for c in " \t\n\r"):
        return False
    return True


def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _find_extra_links(html: str, base_url: str) -> list[str]:
    """Return de‑duped URLs from the homepage that look pricing/course related."""
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    results: list[str] = []
    base_domain = _domain(base_url)

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        full_url = urljoin(base_url, href)

        if _domain(full_url) != base_domain:
            continue
        if full_url in seen:
            continue

        if LINK_KEYWORDS.search(href) or LINK_KEYWORDS.search(text):
            seen.add(full_url)
            results.append(full_url)

    return results


def _img_ext(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in IMAGE_EXTENSIONS | SKIP_EXTENSIONS:
        if path.endswith(ext):
            return ext
    return ".jpg"


def _should_skip_url(src: str) -> bool:
    if not src or src.startswith("data:"):
        return True
    ext = _img_ext(src)
    if ext in SKIP_EXTENSIONS:
        return True
    if STOCK_CDN_PATTERNS.search(src):
        return True
    filename = urlparse(src).path.rsplit("/", 1)[-1]
    if GENERIC_FILENAME_PATTERNS.search(filename):
        return True
    return False


def _get_image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Quick dimension check for JPEG/PNG/WebP without PIL."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return (w, h)
    if data[:2] == b"\xff\xd8":  # JPEG
        f = io.BytesIO(data)
        f.read(2)
        while True:
            marker_bytes = f.read(2)
            if len(marker_bytes) < 2:
                break
            marker = struct.unpack(">H", marker_bytes)[0]
            if 0xFFC0 <= marker <= 0xFFC3:
                f.read(3)
                h, w = struct.unpack(">HH", f.read(4))
                return (w, h)
            length_bytes = f.read(2)
            if len(length_bytes) < 2:
                break
            length = struct.unpack(">H", length_bytes)[0]
            f.read(length - 2)
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if data[12:16] == b"VP8 " and len(data) >= 30:
            w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
            h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
            return (w, h)
        if data[12:16] == b"VP8L" and len(data) >= 25:
            bits = struct.unpack("<I", data[21:25])[0]
            w = (bits & 0x3FFF) + 1
            h = ((bits >> 14) & 0x3FFF) + 1
            return (w, h)
    return None


def _attr_contains(tag: Tag, attr: str, keyword: str) -> bool:
    val = tag.get(attr, "")
    if isinstance(val, list):
        val = " ".join(val)
    return keyword.lower() in val.lower()


def _any_attr_contains(tag: Tag, keywords: list[str]) -> bool:
    for attr in ("src", "alt", "class", "id"):
        for kw in keywords:
            if _attr_contains(tag, attr, kw):
                return True
    return False


def _parent_section_contains(tag: Tag, keywords: list[str]) -> bool:
    """Check if any ancestor section/div has id/class matching keywords."""
    for parent in tag.parents:
        if not isinstance(parent, Tag):
            continue
        for attr in ("class", "id"):
            val = parent.get(attr, "")
            if isinstance(val, list):
                val = " ".join(val)
            val = val.lower()
            for kw in keywords:
                if kw in val:
                    return True
    return False


# ── image discovery ──────────────────────────────────────────────────────────

def _discover_images(htmls: list[str], base_url: str) -> dict[str, list[str]]:
    """
    Scan HTML pages for logo, instructor, and training images.
    Returns {"logo": [...], "instructor": [...], "training": [...]}.
    All URLs are absolute, de‑duped, and pre‑filtered.
    """
    logos: list[str] = []
    instructors: list[str] = []
    training: list[str] = []
    seen: set[str] = set()
    base_domain = _domain(base_url)

    for html in htmls:
        soup = BeautifulSoup(html, "lxml")

        for img in soup.find_all("img", src=True):
            src = img["src"]
            full_url = urljoin(base_url, src)

            if _domain(full_url) != base_domain and not full_url.startswith("http"):
                continue
            if full_url in seen:
                continue
            if _should_skip_url(full_url):
                continue

            seen.add(full_url)

            # Logo detection
            if len(logos) < MAX_LOGO:
                in_header = any(
                    isinstance(p, Tag) and p.name == "header"
                    for p in img.parents
                )
                if in_header or _any_attr_contains(img, ["logo"]):
                    logos.append(full_url)
                    continue

            # Instructor photo detection
            if len(instructors) < MAX_INSTRUCTOR:
                instructor_kws = ["about", "team", "instructor", "staff", "bio"]
                if (_any_attr_contains(img, instructor_kws)
                        or _parent_section_contains(img, instructor_kws)):
                    instructors.append(full_url)
                    continue

            # Training/facility photo detection
            if len(training) < MAX_TRAINING:
                training_kws = [
                    "training", "course", "class", "range", "facility",
                    "gallery", "photo", "shoot",
                ]
                if (_any_attr_contains(img, training_kws)
                        or _parent_section_contains(img, training_kws)):
                    training.append(full_url)
                    continue

    return {
        "logo": logos[:MAX_LOGO],
        "instructor": instructors[:MAX_INSTRUCTOR],
        "training": training[:MAX_TRAINING],
    }


# ── crawler ──────────────────────────────────────────────────────────────────

class Crawler:
    """Async‑friendly, rate‑limited HTTP crawler."""

    def __init__(self) -> None:
        self._global_sem = asyncio.Semaphore(GLOBAL_CONCURRENCY)
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._domain_last_request: dict[str, float] = {}
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def _get_domain_lock(self, domain: str) -> asyncio.Lock:
        if domain not in self._domain_locks:
            self._domain_locks[domain] = asyncio.Lock()
        return self._domain_locks[domain]

    async def _throttle(self, domain: str) -> None:
        last = self._domain_last_request.get(domain, 0)
        wait = DOMAIN_DELAY - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)
        self._domain_last_request[domain] = time.monotonic()

    def _sync_get(self, url: str, stream: bool = False, verify: bool = True) -> requests.Response:
        return self._session.get(url, timeout=REQUEST_TIMEOUT, stream=stream, verify=verify)

    def _sync_get_insecure(self, url: str) -> requests.Response:
        # Some public vendor sites have expired/self-signed/misconfigured certs.
        # Keep the default path strict, then fall back only after an SSL failure.
        return self._sync_get(url, verify=False)

    async def fetch(self, url: str) -> requests.Response | None:
        domain = _domain(url)
        lock = self._get_domain_lock(domain)

        async with lock:
            await self._throttle(domain)
            async with self._global_sem:
                loop = asyncio.get_running_loop()
                for attempt in range(1 + MAX_RETRIES):
                    try:
                        resp = await loop.run_in_executor(None, self._sync_get, url)
                        if resp.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                            logger.warning("Retryable %s on %s (attempt %d)", resp.status_code, url, attempt + 1)
                            await asyncio.sleep(2 ** attempt)
                            continue
                        resp.raise_for_status()
                        return resp
                    except requests.exceptions.SSLError as exc:
                        logger.warning("SSL error %s: %s; retrying without certificate verification", url, exc)
                        try:
                            resp = await loop.run_in_executor(None, self._sync_get_insecure, url)
                            resp.raise_for_status()
                            return resp
                        except Exception as insecure_exc:
                            if attempt < MAX_RETRIES:
                                logger.warning("Insecure retry error %s (attempt %d): %s", url, attempt + 1, insecure_exc)
                                await asyncio.sleep(2 ** attempt)
                            else:
                                logger.error("Insecure retry failed after %d attempts: %s – %s", MAX_RETRIES + 1, url, insecure_exc)
                    except Exception as exc:
                        if attempt < MAX_RETRIES:
                            logger.warning("Request error %s (attempt %d): %s", url, attempt + 1, exc)
                            await asyncio.sleep(2 ** attempt)
                        else:
                            logger.error("Failed after %d attempts: %s – %s", MAX_RETRIES + 1, url, exc)

                return None

    async def fetch_image(self, url: str) -> bytes | None:
        """Download an image, enforcing the size limit and dimension check."""
        domain = _domain(url)
        lock = self._get_domain_lock(domain)

        async with lock:
            await self._throttle(domain)
            async with self._global_sem:
                loop = asyncio.get_running_loop()
                try:
                    resp = await loop.run_in_executor(
                        None, lambda: self._sync_get(url, stream=True)
                    )
                    resp.raise_for_status()

                    content_length = resp.headers.get("content-length")
                    if content_length and int(content_length) > MAX_IMAGE_BYTES:
                        logger.debug("Skipping oversized image: %s (%s bytes)", url, content_length)
                        return None

                    data = resp.content
                    if len(data) > MAX_IMAGE_BYTES:
                        return None

                    dims = _get_image_dimensions(data)
                    if dims and (dims[0] < MIN_IMAGE_DIM or dims[1] < MIN_IMAGE_DIM):
                        logger.debug("Skipping small image %dx%d: %s", dims[0], dims[1], url)
                        return None

                    return data
                except Exception as exc:
                    logger.debug("Image download failed %s: %s", url, exc)
                    return None

    async def crawl_vendor(self, website_url: str) -> tuple[str, str, list[str]]:
        """Return (combined_text, crawl_status, list_of_html_pages) for a vendor."""
        homepage_html: str | None = None
        resp = await self.fetch(website_url)

        if resp is None and website_url.startswith("https://"):
            http_url = "http://" + website_url[len("https://"):]
            logger.info("Trying HTTP fallback %s", http_url)
            resp = await self.fetch(http_url)

        if resp is not None:
            homepage_html = resp.text
        else:
            for path in FALLBACK_PATHS:
                base = website_url.rstrip("/")
                fallback = base + path
                logger.info("Trying fallback %s", fallback)
                resp = await self.fetch(fallback)
                if resp is None and fallback.startswith("https://"):
                    http_fallback = "http://" + fallback[len("https://"):]
                    logger.info("Trying HTTP fallback %s", http_fallback)
                    resp = await self.fetch(http_fallback)
                if resp is not None:
                    homepage_html = resp.text
                    break

        if homepage_html is None:
            return "", "failed", []

        all_htmls = [homepage_html]
        all_texts = [_extract_text(homepage_html)]

        has_pricing = bool(re.search(r"\$\s?\d", homepage_html))
        if not has_pricing:
            extra_links = _find_extra_links(homepage_html, website_url)[:MAX_EXTRA_PAGES]
            for link in extra_links:
                resp = await self.fetch(link)
                if resp is not None:
                    all_htmls.append(resp.text)
                    all_texts.append(_extract_text(resp.text))

        combined = "\n\n---\n\n".join(all_texts)
        return combined[:TEXT_CHAR_LIMIT], "success", all_htmls

    async def download_images(
        self,
        image_urls: dict[str, list[str]],
        output_dir: Path,
    ) -> dict[str, list[str]]:
        """
        Download categorised image URLs to output_dir.
        Returns {"logo": [rel_paths], "instructor": [...], "training": [...]}.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        saved: dict[str, list[str]] = {"logo": [], "instructor": [], "training": []}

        for category, urls in image_urls.items():
            for idx, url in enumerate(urls):
                data = await self.fetch_image(url)
                if data is None:
                    continue

                ext = _img_ext(url)
                if category == "logo":
                    fname = f"logo{ext}"
                else:
                    fname = f"{category}_{idx + 1}{ext}"

                dest = output_dir / fname
                dest.write_bytes(data)
                saved[category].append(str(dest))
                logger.info("Saved %s -> %s", url, dest)

        return saved


# ── Claude enrichment ────────────────────────────────────────────────────────

def _call_claude(client: anthropic.Anthropic, vendor_name: str, city: str, state: str, page_text: str) -> dict[str, Any]:
    location = f"{city}, {state}" if city and state else (city or state or "Unknown")
    user_msg = f"Vendor: {vendor_name}, Location: {location}\n\n--- Website content ---\n{page_text}"

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    return json.loads(raw)


async def _call_claude_with_retry(
    client: anthropic.Anthropic,
    vendor_name: str,
    city: str,
    state: str,
    page_text: str,
) -> dict[str, Any]:
    """Retry Claude calls with exponential backoff + jitter for transient failures."""
    loop = asyncio.get_running_loop()
    last_exc: Exception | None = None

    for attempt in range(CLAUDE_MAX_RETRIES + 1):
        try:
            return await loop.run_in_executor(
                None,
                _call_claude,
                client,
                vendor_name,
                city,
                state,
                page_text,
            )
        except json.JSONDecodeError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt >= CLAUDE_MAX_RETRIES:
                break

            backoff = CLAUDE_RETRY_BASE_SECONDS * (2 ** attempt)
            jitter = random.uniform(0, 0.5 * backoff)
            sleep_for = backoff + jitter
            logger.warning(
                "[%s] Claude call failed (attempt %d/%d): %s; retrying in %.1fs",
                vendor_name,
                attempt + 1,
                CLAUDE_MAX_RETRIES + 1,
                exc,
                sleep_for,
            )
            await asyncio.sleep(sleep_for)

    if last_exc is None:
        raise RuntimeError("Claude call failed with unknown error")
    raise last_exc


async def _enrich_one(
    client: anthropic.Anthropic,
    crawler: Crawler,
    row: dict[str, str],
    images_base: Path,
    claude_sem: asyncio.Semaphore,
) -> dict[str, Any]:
    """Enrich a single vendor row; never raises."""
    out: dict[str, Any] = {col: None for col in OUTPUT_COLUMNS}
    out["county"] = row.get("county", "")
    out["needs_review"] = row.get("needs_review", "") or ""
    out["vendor_name"] = row.get("vendor_name", "")
    out["instructor_names"] = row.get("instructor_names", "")
    out["email"] = row.get("email", "")
    out["phone"] = row.get("phone", "")
    out["website_url"] = row.get("website_url", "")
    out["city"] = row.get("city", "")
    out["state"] = row.get("state", "")
    out["enriched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    website = (row.get("website_url") or "").strip()
    if not website:
        out["crawl_status"] = "no_website"
        logger.info("[%s] No website — skipping", out["vendor_name"])
        return out
    if not _is_usable_http_url(website):
        out["crawl_status"] = "no_website"
        logger.info("[%s] Not a usable http(s) URL — skipping (%r)", out["vendor_name"], website[:80])
        return out

    try:
        page_text, crawl_status, htmls = await crawler.crawl_vendor(website)
        out["crawl_status"] = crawl_status

        if crawl_status != "success" or not page_text.strip():
            logger.warning("[%s] Crawl %s", out["vendor_name"], crawl_status)
            return out

        # ── Claude extraction (semaphore limits parallel API usage) ───
        async with claude_sem:
            data = await _call_claude_with_retry(
                client,
                out["vendor_name"],
                out["city"],
                out["state"],
                page_text,
            )

        for field in ENRICHMENT_FIELDS:
            val = data.get(field)
            if val is not None:
                out[field] = val

        # ── Image discovery & download ───────────────────────────────
        slug = _vendor_slug(website)
        image_urls = _discover_images(htmls, website)
        vendor_img_dir = images_base / slug

        saved = await crawler.download_images(image_urls, vendor_img_dir)

        if saved["logo"]:
            out["logo_path"] = _relative_image_path(saved["logo"][0], images_base)
        if saved["instructor"]:
            out["instructor_image_paths"] = "|".join(
                _relative_image_path(p, images_base) for p in saved["instructor"]
            )
        if saved["training"]:
            out["training_image_paths"] = "|".join(
                _relative_image_path(p, images_base) for p in saved["training"]
            )

    except json.JSONDecodeError as exc:
        logger.error("[%s] Claude returned invalid JSON: %s", out["vendor_name"], exc)
        out["crawl_status"] = "parse_error"
    except Exception as exc:
        logger.error("[%s] Unexpected error: %s", out["vendor_name"], exc)
        if out["crawl_status"] is None:
            out["crawl_status"] = "failed"

    return out


def _relative_image_path(abs_path: str, images_base: Path) -> str:
    """Convert absolute path to a path relative to images_base's parent (data/enriched/)."""
    try:
        return str(Path(abs_path).relative_to(images_base.parent))
    except ValueError:
        return abs_path


# ── public API ───────────────────────────────────────────────────────────────

def _county_images_dir(output_dir: Path, county: str) -> Path:
    """Per-county folder under output_dir/images/{county}/ for vendor-slug subdirs."""
    c = (county or "").strip().lower() or "unknown"
    return output_dir / "images" / c


async def enrich_vendors(
    rows: list[dict[str, str]],
    api_key: str,
    output_dir: str | Path = "data/enriched",
) -> list[dict[str, Any]]:
    """Enrich a list of vendor CSV rows. Returns enriched dicts in the same order as input."""
    client = anthropic.Anthropic(api_key=api_key)
    crawler = Crawler()
    out_path = Path(output_dir)
    claude_sem = asyncio.Semaphore(CLAUDE_CONCURRENCY)

    tasks = [
        _enrich_one(
            client,
            crawler,
            row,
            _county_images_dir(out_path, row.get("county", "")),
            claude_sem,
        )
        for row in rows
    ]
    results = await asyncio.gather(*tasks)
    return list(results)


def load_vendors(csv_path: str | Path, county: str | None = None) -> list[dict[str, str]]:
    """Load vendor rows from the all‑vendors CSV, optionally filtering by county."""
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if county and row.get("county", "").strip().lower() != county.strip().lower():
                continue
            rows.append(row)
    return rows


def write_enriched_csv(rows: list[dict[str, Any]], output_path: str | Path) -> None:
    """Write enriched rows to a CSV with the canonical column order."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
