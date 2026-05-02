"""
Pre-Supabase cleanup for data/enriched/all-vendors.csv.

Applies the following fixes:
  1. Strip trailing whitespace from enrichment_confidence
  2. Remove exact duplicate rows (same vendor_name + county)
  3. Remove 'Approved CCW Instructors' placeholder rows
  4. Replace 'Private Instructor' vendor_name with instructor_names; delete if blank
  5. Fix multi-location/slash city values — pick the city that matches the county
  6. Blank out non-city city values (county names, region strings, "Online", etc.)
  7. Fill empty state with 'CA'
"""

import csv
import re
import shutil
from pathlib import Path

INPUT = Path("data/enriched/all-vendors.csv")
BACKUP = Path("data/enriched/all-vendors.backup-before-supabase-cleanup.csv")
OUTPUT = INPUT


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


def main():
    with open(INPUT, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    print(f"Input rows: {len(rows)}")

    # Back up original
    shutil.copy(INPUT, BACKUP)
    print(f"Backup saved to {BACKUP}")

    cleaned = []
    seen_key: set[tuple] = set()
    removed_reasons: list[str] = []

    for r in rows:
        vname = r["vendor_name"].strip()
        county = r["county"].strip()

        # 1. Strip trailing whitespace from enrichment_confidence
        r["enrichment_confidence"] = r["enrichment_confidence"].strip()

        # 2. Remove exact duplicates (same vendor_name + county)
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

        # 5 & 6. Fix city field
        r["city"] = clean_city(r["city"], county)

        # 7. Fill empty state with CA
        if not r["state"].strip():
            r["state"] = "CA"

        cleaned.append(r)

    print(f"Output rows: {len(cleaned)}")
    print(f"Removed {len(removed_reasons)} rows:")
    for msg in removed_reasons:
        print(f"  - {msg}")

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cleaned)

    print(f"\nWrote cleaned file to {OUTPUT}")


if __name__ == "__main__":
    main()
