"""
Shared helpers for GSC URL matching and production instructor profile slugs.
"""

from __future__ import annotations

import csv
import os
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = Path(__file__).resolve().parents[1]
GSC_DIR = SCRAPER_ROOT / "data" / "gsc"
AUDIT_DIR = SCRAPER_ROOT / "data" / "audit"
CSV_PATH = SCRAPER_ROOT / "data" / "enriched" / "all-vendors.csv"
INDEXED_CSV = GSC_DIR / "gsc-indexed-valid-2026-07-01.csv"
DISCOVERED_CSV = GSC_DIR / "gsc-discovered-not-indexed-2026-07-01.csv"
SLUG_CACHE = GSC_DIR / "production-instructor-slugs.txt"
PROFILE_BASE = "https://www.getcarryclass.com/instructors"

CA_COUNTIES = {
    "alameda", "alpine", "amador", "butte", "calaveras", "colusa", "contra-costa",
    "del-norte", "el-dorado", "fresno", "glenn", "humboldt", "imperial", "inyo",
    "kern", "kings", "lake", "lassen", "los-angeles", "madera", "marin", "mariposa",
    "mendocino", "merced", "modoc", "mono", "monterey", "napa", "nevada", "orange",
    "placer", "plumas", "riverside", "sacramento", "san-benito", "san-bernardino",
    "san-diego", "san-francisco", "san-joaquin", "san-luis-obispo", "san-mateo",
    "santa-barbara", "santa-clara", "santa-cruz", "shasta", "sierra", "siskiyou",
    "solano", "sonoma", "stanislaus", "sutter", "tehama", "trinity", "tulare",
    "tuolumne", "ventura", "yolo", "yuba",
}

_SUFFIX_TOKENS = frozenset({"llc", "inc", "corp", "co", "ltd", "the", "and"})


def normalize_gsc_url(url: str) -> str:
    url = url.strip().lower()
    url = url.split("?")[0].split("#")[0]
    url = url.rstrip("/")
    url = url.replace("://getcarryclass.com", "://www.getcarryclass.com")
    return url


def name_to_slug(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def slug_name_part(slug: str) -> str:
    return slug.rsplit("-", 1)[0]


def _normalize_slug_tokens(name: str) -> list[str]:
    slug = name_to_slug(name)
    tokens = [t for t in slug.split("-") if t and t not in _SUFFIX_TOKENS]
    return tokens


def _slug_similarity(vendor_name: str, slug: str) -> float:
    v_tokens = _normalize_slug_tokens(vendor_name)
    s_tokens = [t for t in slug_name_part(slug).split("-") if t and t not in _SUFFIX_TOKENS]
    if not v_tokens or not s_tokens:
        return 0.0
    v_set, s_set = set(v_tokens), set(s_tokens)
    jaccard = len(v_set & s_set) / len(v_set | s_set)
    seq = SequenceMatcher(None, "-".join(v_tokens), "-".join(s_tokens)).ratio()
    return 0.55 * jaccard + 0.45 * seq


def _domain_slug(url: str) -> str:
    if not url:
        return ""
    host = urlparse(url.strip()).netloc.lower().replace("www.", "")
    return host.replace(".", "-")


def load_indexed_urls(path: Path = INDEXED_CSV) -> set[str]:
    urls: set[str] = set()
    if not path.exists():
        return urls
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = (row.get("URL") or row.get("url") or "").strip()
            if "/instructors/" in raw:
                urls.add(normalize_gsc_url(raw))
    return urls


def load_discovered_not_indexed_urls(path: Path = DISCOVERED_CSV) -> set[str] | None:
    if not path.exists():
        return None
    urls: set[str] = set()
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = (row.get("URL") or row.get("url") or "").strip()
            if "/instructors/" in raw:
                urls.add(normalize_gsc_url(raw))
    return urls if urls else None


def fetch_production_slugs(cache_path: Path = SLUG_CACHE, refresh: bool = False) -> list[str]:
    if cache_path.exists() and not refresh:
        return [ln.strip() for ln in cache_path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    resp = requests.get(
        "https://www.getcarryclass.com/instructors",
        timeout=30,
        headers={"User-Agent": "CCWDirectory/1.0 (audit script)"},
    )
    resp.raise_for_status()
    slugs = sorted(set(re.findall(r"/instructors/([a-z0-9][a-z0-9-]+)", resp.text)))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("\n".join(slugs) + "\n", encoding="utf-8")
    return slugs


def build_slug_index(slugs: list[str]) -> dict[str, list[str]]:
    by_name: dict[str, list[str]] = defaultdict(list)
    for slug in slugs:
        by_name[slug_name_part(slug)].append(slug)
    return dict(by_name)


def resolve_profile_slug(
    vendor_name: str,
    website_url: str = "",
    slug_index: dict[str, list[str]] | None = None,
    all_slugs: list[str] | None = None,
) -> tuple[str, str]:
    """
    Return (profile_slug, match_method).
    match_method: exact | domain | fuzzy | constructed | ambiguous_exact
    """
    name_slug = name_to_slug(vendor_name)
    if slug_index is None:
        all_slugs = all_slugs or fetch_production_slugs()
        slug_index = build_slug_index(all_slugs)

    exact = slug_index.get(name_slug, [])
    if len(exact) == 1:
        return exact[0], "exact"
    if len(exact) > 1:
        dom = _domain_slug(website_url)
        if dom:
            for slug in exact:
                if dom[:12] in slug or slug_name_part(slug).startswith(dom[:8]):
                    return slug, "domain"
        return exact[0], "ambiguous_exact"

    dom = _domain_slug(website_url)
    if dom and all_slugs:
        dom_hits = [s for s in all_slugs if dom.split("-")[0] in s]
        if len(dom_hits) == 1:
            return dom_hits[0], "domain"

    if all_slugs:
        scored = sorted(
            ((s, _slug_similarity(vendor_name, s)) for s in all_slugs),
            key=lambda x: x[1],
            reverse=True,
        )
        if scored and scored[0][1] >= 0.72:
            return scored[0][0], "fuzzy"

    return name_slug, "constructed"


def profile_url_from_slug(slug: str) -> str:
    return f"{PROFILE_BASE}/{slug}"


def gsc_status_for_url(profile_url: str, indexed_urls: set[str]) -> str:
    normalized = normalize_gsc_url(profile_url)
    if normalized in indexed_urls:
        return "indexed"
    slug = normalized.split("/instructors/")[-1] if "/instructors/" in normalized else ""
    if slug and len(slug.rsplit("-", 1)[-1]) == 10 and re.fullmatch(
        r"[a-f0-9]{10}", slug.rsplit("-", 1)[-1]
    ):
        return "not_indexed"
    return "unknown"


def eligible_for_regeneration(
    uniqueness_score: int,
    profile_url: str,
    indexed_urls: set[str],
    discovered_urls: set[str] | None,
) -> bool:
    if uniqueness_score > 3:
        return False
    if normalize_gsc_url(profile_url) in indexed_urls:
        return False
    if discovered_urls is not None:
        return normalize_gsc_url(profile_url) in discovered_urls
    return True


def load_corpus_rows(prefer_supabase: bool = True) -> list[dict[str, str]]:
    if prefer_supabase:
        rows = _try_load_supabase()
        if rows:
            return rows
    return _load_csv_rows()


def _load_csv_rows() -> list[dict[str, str]]:
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["normalized_vendor_name"] = (r.get("vendor_name") or "").strip().lower()
        r.setdefault("id", "")
    return rows


def _try_load_supabase() -> list[dict[str, str]] | None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return None

    for env_path in (REPO_ROOT / ".env.local", SCRAPER_ROOT / ".env"):
        if env_path.exists():
            load_dotenv(env_path)

    base = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base or not key:
        return None

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    select = (
        "id,county,vendor_name,normalized_vendor_name,vendor_description,"
        "website_url,crawl_status,enrichment_confidence,confidence_notes,"
        "instructor_names,city,address,state,phone,email,"
        "price_16hr_full,price_8hr_renewal,price_add_a_gun,"
        "booking_capability,logo_path,instructor_image_paths,training_image_paths,enriched_at"
    )
    rows: list[dict[str, str]] = []
    offset = 0
    page_size = 1000
    while True:
        url = (
            f"{base}/rest/v1/carry_class_vendor_data"
            f"?select={select}"
            f"&vendor_description=not.is.null"
            f"&offset={offset}&limit={page_size}"
        )
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code != 200:
            print(f"Supabase fetch failed ({resp.status_code}); falling back to CSV", file=sys.stderr)
            return None
        batch = resp.json()
        if not batch:
            break
        for r in batch:
            desc = (r.get("vendor_description") or "").strip()
            if not desc:
                continue
            rows.append({k: ("" if v is None else str(v)) for k, v in r.items()})
        if len(batch) < page_size:
            break
        offset += page_size
    return rows if rows else None


def dedupe_vendors(rows: list[dict[str, str]]) -> tuple[list[dict], dict[str, list[dict]]]:
    """One record per normalized_vendor_name (longest description); map all county rows."""
    by_vendor: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        desc = (r.get("vendor_description") or "").strip()
        if not desc:
            continue
        key = (r.get("normalized_vendor_name") or r.get("vendor_name", "")).strip().lower()
        if not key:
            continue
        by_vendor[key].append(r)

    deduped: list[dict] = []
    county_map: dict[str, list[dict]] = {}
    for key, group in by_vendor.items():
        best = max(group, key=lambda x: len((x.get("vendor_description") or "")))
        counties = sorted({g.get("county", "") for g in group if g.get("county")})
        county_map[key] = group
        record = dict(best)
        record["normalized_vendor_name"] = key
        record["county_rows"] = len(group)
        record["counties_served"] = "|".join(counties)
        record["all_row_ids"] = "|".join(g.get("id", "") for g in group if g.get("id"))
        deduped.append(record)
    return deduped, county_map
