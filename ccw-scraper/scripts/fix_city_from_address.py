"""
One-shot cleanup: fill blank `city` from `address`, clear address-only-city rows.
Operates on data/enriched/all-vendors.csv.
"""

import csv
import re
import shutil
from pathlib import Path

SRC = Path("data/enriched/all-vendors.csv")
BACKUP = SRC.with_name("all-vendors.backup-before-city-fix.csv")

# ── helpers ──────────────────────────────────────────────────────────────────

CA_STATE_PAT = r"(?:CA|California)"
ANY_STATE_PAT = r"(?:[A-Z]{2}|California)"
ZIP_PAT = r"(?:\s+\d{5}(?:-\d{4})?)?"
COUNTRY_TAIL = r"(?:,\s*United\s+States)?"

# Matches addresses that are ONLY "City, CA [zip]" with no street component
CITY_ONLY_RE = re.compile(
    rf"^([A-Za-z .'\-]+),\s*{CA_STATE_PAT}{ZIP_PAT}{COUNTRY_TAIL}\s*$"
)

STREET_SUFFIXES = {
    "st", "street", "ave", "avenue", "blvd", "boulevard", "dr", "drive",
    "rd", "road", "ln", "lane", "way", "ct", "court", "pl", "place",
    "pkwy", "parkway", "hwy", "highway", "cir", "circle", "ter",
    "terrace", "trl", "trail", "loop",
}

CITY_FROM_ADDR_PATTERNS = [
    # standard:  ..., City, STATE [zip][, country]
    re.compile(
        rf",\s*([A-Za-z .'\-]+?)\s*,\s*{ANY_STATE_PAT}{ZIP_PAT}{COUNTRY_TAIL}\s*$"
    ),
    # extra comma after CA:  ..., City, CA, zip
    re.compile(
        r",\s*([A-Za-z .'\-]+?)\s*,\s*CA\s*,\s*\d{5}(?:-\d{4})?\s*$"
    ),
    # no comma before state:  ..., City CA zip  or  ... City CA zip
    re.compile(
        rf"[\s,]\s*([A-Za-z .'\-]{{2,}}?)\s+CA\s+\d{{5}}(?:-\d{{4}})?\s*$"
    ),
    # period before city (e.g. "595 W Line St. Bishop, CA 93514")
    re.compile(
        rf"\.\s+([A-Za-z .'\-]+?)\s*,\s*{CA_STATE_PAT}{ZIP_PAT}\s*$"
    ),
    # newline before city (e.g. "4667 Golden Foothill Pkwy\nEl Dorado Hills, CA")
    re.compile(
        rf"\n\s*([A-Za-z .'\-]+?)\s*,\s*{CA_STATE_PAT}{ZIP_PAT}\s*$"
    ),
    # P.O. BOX NNN CITY, CA ZIP
    re.compile(
        rf"P\.?O\.?\s*(?:BOX|Box)\s+\d+\s+([A-Za-z .'\-]+?)\s*,\s*{CA_STATE_PAT}{ZIP_PAT}\s*$"
    ),
    # missing state but has zip:  ..., City, 9xxxx
    re.compile(
        r",\s*([A-Za-z .'\-]+?)\s*,\s*\d{5}(?:-\d{4})?\s*$"
    ),
]


def _extract_city_fallback(address):
    """Handle addresses with no comma before city (e.g. '6th Street Eureka, CA')."""
    # Find state marker position
    m = re.search(r",\s*(?:CA|California)(?:\s+\d{5}|\s*$)", address)
    if not m:
        return None
    before = address[:m.start()].strip()
    words = before.split()
    if not words:
        return None
    # Walk backwards collecting capitalized words until we hit a number,
    # a street suffix, a unit indicator, or a lowercase word
    city_words = []
    for w in reversed(words):
        cleaned = re.sub(r"[.,#\-]", "", w)
        if re.match(r"^\d", cleaned):
            break
        if cleaned.lower() in STREET_SUFFIXES:
            break
        if cleaned.lower() in ("unit", "ste", "suite", "apt", "bldg"):
            break
        if cleaned and cleaned[0].isupper():
            city_words.insert(0, w.strip(","))
        else:
            break
    if city_words:
        candidate = " ".join(city_words)
        if len(candidate) > 1:
            return candidate
    return None


def _extract_city_dash(address):
    """Handle dash-separated city (e.g. '1040 5th Street - Novato')."""
    m = re.search(r"\s+-\s+([A-Za-z .'\-]+?)\s*$", address)
    if m:
        candidate = m.group(1).strip()
        if candidate and len(candidate) > 1:
            return candidate
    return None


def extract_city(address):
    """Return the city parsed from *address*, or None."""
    for pat in CITY_FROM_ADDR_PATTERNS:
        m = pat.search(address)
        if m:
            candidate = m.group(1).strip()
            if candidate and len(candidate) > 1:
                return candidate
    # Fallback: no-comma-before-city CA addresses
    result = _extract_city_fallback(address)
    if result:
        return result
    # Fallback: dash separator
    return _extract_city_dash(address)


def is_city_only(address: str) -> bool:
    return bool(CITY_ONLY_RE.match(address.strip()))


def is_blank(val: str) -> bool:
    return val.strip().lower() in ("", "null", "none", "nan")


# ── main ─────────────────────────────────────────────────────────────────────

shutil.copy2(SRC, BACKUP)
print(f"Backup → {BACKUP}")

with open(SRC, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    rows = list(reader)

city_filled = []
addr_cleared = []

for row in rows:
    city = row.get("city", "")
    addr = row.get("address", "")
    old_city = city
    old_addr = addr

    changed = False

    # Rule 1: fill blank city from address
    if is_blank(city) and addr.strip():
        if is_city_only(addr):
            m = CITY_ONLY_RE.match(addr.strip())
            if m:
                row["city"] = m.group(1).strip()
                changed = True
        else:
            extracted = extract_city(addr)
            if extracted:
                row["city"] = extracted
                changed = True

    # Rule 2: clear city-only addresses
    if is_city_only(addr):
        row["address"] = ""
        changed = True

    if changed:
        if row["city"] != old_city:
            city_filled.append((row["vendor_name"], old_city, row["city"], old_addr, row["address"]))
        if row["address"] != old_addr:
            addr_cleared.append((row["vendor_name"], row["city"], old_addr, row["address"]))

with open(SRC, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

# ── report ───────────────────────────────────────────────────────────────────

print(f"\nTotal rows processed: {len(rows)}")
print(f"City filled from address: {len(city_filled)}")
print(f"Address cleared (city-only pattern): {len(addr_cleared)}")

print("\n── First 10 city-filled rows ──")
for vendor, oc, nc, oa, na in city_filled[:10]:
    print(f"  {vendor}")
    print(f"    city:    {oc!r} → {nc!r}")
    print(f"    address: {oa!r} → {na!r}")

print("\n── First 10 address-cleared rows ──")
for vendor, c, oa, na in addr_cleared[:10]:
    print(f"  {vendor}")
    print(f"    city:    {c!r}")
    print(f"    address: {oa!r} → {na!r}")

# ── sanity check ─────────────────────────────────────────────────────────────

still_missing = sum(1 for r in rows if is_blank(r.get("city", "")) and r.get("address", "").strip())
still_city_only = sum(1 for r in rows if is_city_only(r.get("address", "")))

print(f"\n── Sanity check ──")
print(f"Rows still blank city + non-empty address: {still_missing}")
print(f"Rows still with city-only address pattern: {still_city_only}")

if still_missing:
    print("\n  Examples of remaining blank-city rows:")
    for r in rows:
        if is_blank(r.get("city", "")) and r.get("address", "").strip():
            print(f"    {r['vendor_name']!r}: address={r['address']!r}")
            still_missing -= 1
            if still_missing <= len(rows) - 5:
                break
