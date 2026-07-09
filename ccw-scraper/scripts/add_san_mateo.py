#!/usr/bin/env python3
"""Add 16 San Mateo County vendors from the Feb 24, 2026 CCW applicant memo."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from urllib.parse import urlparse

CSV_PATH = "data/enriched/all-vendors.csv"
TIMESTAMP = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

# Approved vendors from San Mateo County Sheriff CCW Vendor Memo (02-24-26)
SAN_MATEO_VENDORS = [
    {
        "vendor_name": "Saber Tactics",
        "website_url": "https://sabertactics.com/",
        "phone": "650-276-0009",
        "email": "training@sabertactics.com",
        "city": "Morgan Hill & Los Gatos",
        "match_domains": {"sabertactics.com"},
    },
    {
        "vendor_name": "Gun Kraft",
        "website_url": "https://www.gunkraft.com/",
        "phone": "408-515-3536",
        "email": "robin@gunkraft.com",
        "city": "San Leandro",
        "match_domains": {"gunkraft.com"},
    },
    {
        "vendor_name": "Bay Area Tactical Group",
        "website_url": "https://www.battactical.com/",
        "phone": "415-568-6803",
        "email": "info@bayareatacticalgroup.com",
        "city": "TBD",
        "match_domains": {"battactical.com"},
    },
    {
        "vendor_name": "Bay Profs Training Group",
        "website_url": "https://bayprofs.org/contact/",
        "phone": "650-395-7189",
        "email": "bayprofs@bayprofs.org",
        "city": "Concord",
        "match_domains": {"bayprofs.org"},
    },
    {
        "vendor_name": "2nd Amendment Firearms Academy",
        "website_url": "https://www.2afirearmsacademy.com/",
        "phone": "707-410-0389",
        "email": "",
        "city": "TBD",
        "match_domains": {"2afirearmsacademy.com"},
    },
    {
        "vendor_name": "Defensive Accuracy",
        "website_url": "https://www.daccw.com/",
        "phone": "408-687-3791",
        "email": "",
        "city": "Concord & Richmond",
        "match_domains": {"daccw.com"},
    },
    {
        "vendor_name": "ASP Firearm Training",
        "website_url": "https://aspfirearm.square.site/",
        "phone": "800-279-1780",
        "email": "ASPCorpTraining@gmail.com",
        "city": "San Jose",
        "match_domains": {"aspfirearm.square.site", "aspfirearms.com", "aspfirearm.com"},
    },
    {
        "vendor_name": "Execushield Inc.",
        "website_url": "https://execushield.com/ccwcourse/",
        "phone": "510-626-4940",
        "email": "",
        "city": "Richmond",
        "match_domains": {"execushield.com"},
    },
    {
        "vendor_name": "CoCo Firearm Training LLC",
        "website_url": "https://cocofirearmtraining.com/",
        "phone": "925-384-1920",
        "email": "Tim@CocoFirearmTraining.com",
        "city": "Concord",
        "match_domains": {"cocofirearmtraining.com"},
    },
    {
        "vendor_name": "Grover Group",
        "website_url": "https://ggccw.biz",
        "phone": "510-676-6076",
        "email": "anoop@grovergroup.biz",
        "city": "Morgan Hill/Concord",
        "match_domains": {"ggccw.biz"},
    },
    {
        "vendor_name": "AAO-CO Firearms Training",
        "website_url": "https://aao-co.com/",
        "phone": "707-400-3677",
        "email": "bryan@aao-co.com",
        "city": "Sonoma",
        "match_domains": {"aao-co.com"},
    },
    {
        "vendor_name": "Silicon Valley Tactical",
        "website_url": "https://www.siliconvalleytactical.com",
        "phone": "408-313-1254",
        "email": "",
        "city": "San Jose",
        "match_domains": {"siliconvalleytactical.com"},
    },
    {
        "vendor_name": "Security Six",
        "website_url": "https://securitysix.com",
        "phone": "510-305-2881",
        "email": "",
        "city": "Tracy",
        "match_domains": {"securitysix.com"},
        "new_vendor": True,
    },
    {
        "vendor_name": "Triple Point Solutions",
        "website_url": "",
        "phone": "925-506-8669",
        "email": "INFO@triplepointsolutions.com",
        "city": "Concord",
        "match_domains": set(),
        "new_vendor": True,
    },
    {
        "vendor_name": "McGrew & Associates, Inc.",
        "website_url": "https://mcgrewpi.com/",
        "phone": "408-647-4567",
        "email": "",
        "city": "San Jose",
        "match_domains": {"mcgrewpi.com"},
    },
    {
        "vendor_name": "LEO Defensive Concepts, LLC",
        "website_url": "https://leodefensiveconcepts.com",
        "phone": "209-321-9692",
        "email": "info@leodefensiveconcepts.com",
        "city": "Livermore",
        "match_domains": {"leodefensiveconcepts.com"},
    },
]

CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, "": 0}
STATUS_RANK = {"success": 2, "failed": 1, "": 0}


def domain(url: str) -> str:
    if not url:
        return ""
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    return host.removeprefix("www.")


def find_best_source(rows: list[dict], match_domains: set[str]) -> dict | None:
    candidates = [
        r for r in rows
        if domain(r.get("website_url", "")) in match_domains
        and r.get("crawl_status") == "success"
    ]
    if not candidates:
        candidates = [r for r in rows if domain(r.get("website_url", "")) in match_domains]
    if not candidates:
        return None

    def score(row: dict) -> tuple:
        return (
            STATUS_RANK.get(row.get("crawl_status", ""), 0),
            CONFIDENCE_RANK.get(row.get("enrichment_confidence", ""), 0),
            1 if row.get("vendor_description") else 0,
            1 if row.get("price_16hr_full") else 0,
        )

    return max(candidates, key=score)


def blank_row(fieldnames: list[str]) -> dict:
    return {k: "" for k in fieldnames}


def main() -> None:
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        existing = list(reader)

    if any(r.get("county") == "san-mateo" for r in existing):
        raise SystemExit("san-mateo rows already exist in all-vendors.csv")

    new_rows: list[dict] = []
    relisted = 0
    needs_scrape: list[str] = []

    for vendor in SAN_MATEO_VENDORS:
        row = blank_row(fieldnames)
        source = find_best_source(existing, vendor["match_domains"])

        if source:
            row.update({k: source.get(k, "") for k in fieldnames})
            relisted += 1
            notes = row.get("confidence_notes", "")
            prefix = f"Re-listed from {source.get('county', 'unknown')} county entry for San Mateo County memo (02-24-26)."
            row["confidence_notes"] = f"{prefix} {notes}".strip()
        else:
            needs_scrape.append(vendor["vendor_name"])
            row["crawl_status"] = "pending"
            row["enrichment_confidence"] = ""
            row["confidence_notes"] = (
                "New vendor from San Mateo County memo (02-24-26). Requires full website scrape."
            )

        row["county"] = "san-mateo"
        row["needs_review"] = ""
        row["vendor_name"] = vendor["vendor_name"]
        row["phone"] = vendor["phone"]
        row["email"] = vendor.get("email") or row.get("email", "")
        row["city"] = vendor["city"]
        row["state"] = "CA"
        row["website_url"] = vendor.get("website_url") or row.get("website_url", "")
        row["enriched_at"] = TIMESTAMP

        if vendor.get("new_vendor"):
            row["logo_path"] = ""
            row["instructor_image_paths"] = ""
            row["training_image_paths"] = ""
            row["google_place_id"] = ""
            row["google_reviews_url"] = ""
            row["match_confidence"] = ""
            row["match_reason"] = ""
            row["raw_candidate_place_ids"] = ""
            row["error_message"] = ""

        new_rows.append(row)

    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerows(new_rows)

    print(f"Appended {len(new_rows)} san-mateo vendor rows to {CSV_PATH}")
    print(f"  Re-listed from existing enrichment: {relisted}")
    print(f"  Need full scrape: {len(needs_scrape)}")
    for name in needs_scrape:
        print(f"    - {name}")


if __name__ == "__main__":
    main()
