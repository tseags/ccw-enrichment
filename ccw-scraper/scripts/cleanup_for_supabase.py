"""
Pre-Supabase cleanup for data/enriched/all-vendors.csv.

This file is the canonical vendor dataset for Supabase loads (source of truth).

Applies the following fixes:
  1. Strip trailing whitespace from enrichment_confidence
  2. Remove exact duplicate rows (same vendor_name + county)
  3. Remove 'Approved CCW Instructors' placeholder rows
  4. Replace 'Private Instructor' vendor_name with instructor_names; delete if blank
  5. Fix multi-location/slash city values — pick the city that matches the county
  6. Blank out non-city city values (county names, region strings, "Online", etc.)
  7. Fill empty state with 'CA'
  8. Normalize US phone numbers to NPA-NXX-XXXX (dots/parens/spaces; optional leading 1;
     multiple numbers joined with " / "; trailing ext. preserved)
  9. Normalize county slug to match supabase/migrations/0003_seed_california_counties.sql
 10. Set needs_review for rows that need manual verification (unknown county, bad phone,
     crawl failed). Vendors listed in multiple counties may legitimately have different
     contact info per county; that is not flagged here (merge/present on the site).
"""

from __future__ import annotations

import csv
import re
import shutil
from pathlib import Path

INPUT = Path("data/enriched/all-vendors.csv")
BACKUP = Path("data/enriched/all-vendors.backup-before-supabase-cleanup.csv")
OUTPUT = INPUT

# Must match supabase/migrations/0003_seed_california_counties.sql
ALLOWED_COUNTY_SLUGS = frozenset(
    {
        "alameda",
        "alpine",
        "amador",
        "butte",
        "calaveras",
        "colusa",
        "contra-costa",
        "del-norte",
        "el-dorado",
        "fresno",
        "glenn",
        "humboldt",
        "imperial",
        "inyo",
        "kern",
        "kings",
        "lake",
        "lassen",
        "los-angeles",
        "madera",
        "marin",
        "mariposa",
        "mendocino",
        "merced",
        "modoc",
        "mono",
        "monterey",
        "napa",
        "nevada",
        "orange",
        "placer",
        "plumas",
        "riverside",
        "sacramento",
        "san-benito",
        "san-bernardino",
        "san-diego",
        "san-francisco",
        "san-joaquin",
        "san-luis-obispo",
        "san-mateo",
        "santa-barbara",
        "santa-clara",
        "santa-cruz",
        "shasta",
        "sierra",
        "siskiyou",
        "solano",
        "sonoma",
        "stanislaus",
        "sutter",
        "tehama",
        "trinity",
        "tulare",
        "tuolumne",
        "ventura",
        "yolo",
        "yuba",
    }
)

# Alternate spellings / ingest filename habits → Supabase slug
COUNTY_SLUG_ALIASES: dict[str, str] = {
    "contracosta": "contra-costa",
    "contra costa": "contra-costa",
    "san diego": "san-diego",
    "san francisco": "san-francisco",
    "san joaquin": "san-joaquin",
    "san luis obispo": "san-luis-obispo",
    "san mateo": "san-mateo",
    "san benito": "san-benito",
    "san bernardino": "san-bernardino",
    "santa clara": "santa-clara",
    "santa cruz": "santa-cruz",
    "santa barbara": "santa-barbara",
    "los angeles": "los-angeles",
    "el dorado": "el-dorado",
    "del norte": "del-norte",
}

# NANP: optional country code 1, area NXX (N=2–9), exchange NXX (N=2–9), line XXXX
_NANP_SEGMENT = re.compile(
    r"(?:\+?1[-.\s]*)?"
    r"\(?([2-9]\d{2})\)?"
    r"[-.\s]*"
    r"([2-9]\d{2})"
    r"[-.\s]*"
    r"(\d{4})\b"
)
_EXT_SUFFIX = re.compile(
    r"(?i)\s*(?:,|;)?\s*(?:ext\.?|extension|x)\s*:?\s*(\d{1,8})\s*$"
)


NON_CITY_EXACT = {
    "online",
    "northern california",
    "several northern california counties",
    "ca locations",
}

# Venue-type words that disqualify a token from being a city (word-boundary matched)
VENUE_PATTERN = re.compile(
    r"\b(?:gun\s+range|shooting\s+range|gun\s+club|armory|gun\s+world)\b",
    re.IGNORECASE,
)


def is_non_city(s: str) -> bool:
    s = s.strip()
    sl = s.lower()
    if sl in NON_CITY_EXACT:
        return True
    # Phrases like "Fresno County", "Fresno & Madera counties", etc.
    if "county" in sl or "counties" in sl:
        return True
    return False


def clean_city_part(p: str) -> str:
    """Normalise a single candidate city token; return '' if it isn't a real city."""
    p = p.strip()
    if not p:
        return ""
    pl = p.lower()

    if pl == "online":
        return ""
    # Bare state abbreviation
    if re.match(r"^[a-z]{2}$", pl):
        return ""
    # "<County name> Co" or "<County name> Co." — e.g. "Lassen Co"
    if re.search(r"\s+co\.?$", pl):
        return ""
    # Contains county/counties
    if "county" in pl or "counties" in pl:
        return ""
    # Venue names that sneak in (Gun Range, Gun Club, Armory, etc.)
    # Use word-boundary regex so "Orange" isn't caught by "range"
    if VENUE_PATTERN.search(p):
        return ""
    # "City CA" or "City NV" — strip the state suffix
    m = re.match(r"^(.+?)\s+([A-Z]{2})$", p)
    if m and m.group(2) in {"CA", "NV", "AZ", "OR", "WA", "ID", "UT"}:
        return m.group(1).strip()

    return p


def clean_city(city: str, county: str) -> str:
    city = city.strip()
    if not city:
        return ""

    # Entire value is a non-city
    if is_non_city(city):
        return ""

    # No splitting needed — still run through part cleaner for edge cases
    if "/" not in city and "," not in city:
        return clean_city_part(city)

    # Split on slashes and commas, clean each part
    parts = re.split(r"[/,]", city)
    candidates = [clean_city_part(p) for p in parts]
    candidates = [c for c in candidates if c]

    if not candidates:
        return ""

    # Prefer the candidate whose name appears in (or matches) the county slug
    county_slug = county.replace("-", " ").lower()
    for c in candidates:
        if county_slug in c.lower() or c.lower() in county_slug:
            return c

    # Fall back to the first surviving candidate
    return candidates[0]


def _nanp_digits_ok(npa: str, nxx: str) -> bool:
    """Loose NANP check: area and exchange first digits are 2–9."""
    return bool(npa and nxx and npa[0] in "23456789" and nxx[0] in "23456789")


def _format_phone(npa: str, nxx: str, line: str) -> str:
    return f"{npa}-{nxx}-{line}"


def normalize_phone(raw: str) -> str:
    """Return US phone as NPA-NXX-XXXX, or multiple joined with ' / '. Unparseable input unchanged (trimmed)."""
    s = raw.strip()
    if not s:
        return ""

    ext_match = _EXT_SUFFIX.search(s)
    ext = ext_match.group(1) if ext_match else None
    core = _EXT_SUFFIX.sub("", s).strip() if ext_match else s

    segments: list[str] = []
    found = _NANP_SEGMENT.findall(core)
    if found:
        for npa, nxx, line in found:
            if _nanp_digits_ok(npa, nxx):
                segments.append(_format_phone(npa, nxx, line))
        if segments:
            out = " / ".join(segments)
            return f"{out} ext. {ext}" if ext else out

    digits = re.sub(r"\D", "", core)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    if len(digits) == 20:
        a, b = digits[:10], digits[10:]
        if _nanp_digits_ok(a[:3], a[3:6]) and _nanp_digits_ok(b[:3], b[3:6]):
            out = f"{_format_phone(a[:3], a[3:6], a[6:])} / {_format_phone(b[:3], b[3:6], b[6:])}"
            return f"{out} ext. {ext}" if ext else out

    if len(digits) == 10 and _nanp_digits_ok(digits[:3], digits[3:6]):
        out = _format_phone(digits[:3], digits[3:6], digits[6:])
        return f"{out} ext. {ext}" if ext else out

    return s


def normalize_county_slug(raw: str) -> tuple[str, str | None]:
    """
    Return (slug, review_reason_or_none). slug is hyphenated lowercase;
    review_reason is 'unknown_county_slug' if not in the Supabase counties seed.
    """
    s = raw.strip().lower().replace("_", "-")
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        return "", "empty_county"
    if s in COUNTY_SLUG_ALIASES:
        s = COUNTY_SLUG_ALIASES[s]
    if s in ALLOWED_COUNTY_SLUGS:
        return s, None
    return s, "unknown_county_slug"


def _phone_well_formed(phone: str) -> bool:
    if not (phone or "").strip():
        return True
    core = re.sub(r"(?i)\s+ext\.\s*\d{1,8}\s*$", "", phone.strip())
    segments = [p.strip() for p in core.split(" / ")]
    seg_pat = re.compile(r"^[2-9]\d{2}-\d{3}-\d{4}$")
    return bool(segments) and all(seg_pat.match(p) for p in segments if p)


def _build_fieldnames(original: list[str] | None) -> list[str]:
    base = list(original or [])
    if "needs_review" in base:
        base.remove("needs_review")
    if "county" in base:
        i = base.index("county") + 1
        base.insert(i, "needs_review")
    else:
        base.append("needs_review")
    return base


def main():
    with open(INPUT, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = _build_fieldnames(reader.fieldnames)
        rows = list(reader)

    print(f"Input rows: {len(rows)}")

    # Back up original
    shutil.copy(INPUT, BACKUP)
    print(f"Backup saved to {BACKUP}")

    cleaned: list[dict[str, str]] = []
    row_flags: list[list[str]] = []
    seen_key: set[tuple[str, str]] = set()
    removed_reasons: list[str] = []

    for r in rows:
        vname = r["vendor_name"].strip()
        raw_county = r.get("county", "").strip()

        county, county_err = normalize_county_slug(raw_county)
        r["county"] = county

        # 1. Strip trailing whitespace from enrichment_confidence
        r["enrichment_confidence"] = r["enrichment_confidence"].strip()

        # 2. Remove exact duplicates (same vendor_name + county) — county is normalized
        key = (vname.lower(), county.lower())
        if key in seen_key:
            removed_reasons.append(f"DUPE: {vname} / {county}")
            continue
        seen_key.add(key)

        # 3. Remove 'Approved CCW Instructors' placeholder
        if vname == "Approved CCW Instructors":
            removed_reasons.append(f"PLACEHOLDER: {vname} / {county}")
            continue

        # 4. Replace 'Private Instructor' with instructor_names or delete
        if vname == "Private Instructor":
            instructor = r["instructor_names"].strip()
            if instructor:
                r["vendor_name"] = instructor
            else:
                removed_reasons.append(f"PRIVATE_INSTRUCTOR_NO_NAME: {county}")
                continue

        vname = r["vendor_name"].strip()

        # 5 & 6. Fix city field (uses normalized county slug)
        r["city"] = clean_city(r["city"], county)

        # 7. Fill empty state with CA
        if not r["state"].strip():
            r["state"] = "CA"

        # 8. Normalize phone to NPA-NXX-XXXX
        r["phone"] = normalize_phone(r.get("phone", ""))

        flags: list[str] = []
        if county_err:
            flags.append(county_err)

        cleaned.append(r)
        row_flags.append(flags)

    # Per-row signals
    for i, r in enumerate(cleaned):
        if r.get("phone", "").strip() and not _phone_well_formed(r["phone"]):
            row_flags[i].append("unparseable_phone")
        if (r.get("crawl_status") or "").strip().lower() == "failed":
            row_flags[i].append("crawl_failed")

    for i, r in enumerate(cleaned):
        uniq = sorted({x for x in row_flags[i] if x})
        r["needs_review"] = "|".join(uniq)

    print(f"Output rows: {len(cleaned)}")
    print(f"Removed {len(removed_reasons)} rows:")
    for msg in removed_reasons:
        print(f"  - {msg}")

    needs_n = sum(1 for r in cleaned if r.get("needs_review"))
    print(f"Rows with needs_review set: {needs_n}")

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(cleaned)

    print(f"\nWrote cleaned file to {OUTPUT}")


if __name__ == "__main__":
    main()
