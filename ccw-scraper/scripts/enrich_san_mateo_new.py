#!/usr/bin/env python3
"""Enrich pending San Mateo vendors and merge back into all-vendors.csv."""

from __future__ import annotations

import asyncio
import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT))

from enrich.enricher import enrich_vendors  # noqa: E402

CSV_PATH = ROOT / "data/enriched/all-vendors.csv"
TARGET_NAMES = {"security six", "triple point solutions"}


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set")

    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    indexes = [
        i for i, row in enumerate(rows)
        if row.get("county") == "san-mateo"
        and (row.get("vendor_name") or "").strip().lower() in TARGET_NAMES
    ]
    if not indexes:
        sys.exit("No pending San Mateo target rows found")

    subset = [dict(rows[i]) for i in indexes]
    print(f"Enriching {len(subset)} vendors:")
    for row in subset:
        print(f"  - {row.get('vendor_name')} | {row.get('website_url')}")

    results = asyncio.run(
        enrich_vendors(subset, api_key, output_dir=CSV_PATH.parent)
    )

    for local_idx, enriched in enumerate(results):
        global_idx = indexes[local_idx]
        merged = dict(rows[global_idx])
        for key, value in enriched.items():
            if value is None:
                continue
            text = str(value).strip()
            if text:
                merged[key] = text
        merged["county"] = "san-mateo"
        notes = (merged.get("confidence_notes") or "").strip()
        prefix = "Scraped for San Mateo County memo (02-24-26)."
        merged["confidence_notes"] = f"{prefix} {notes}".strip()
        rows[global_idx] = merged

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print("\nResults:")
    for row in results:
        print(
            f"  {row.get('vendor_name')}: crawl_status={row.get('crawl_status')}, "
            f"confidence={row.get('enrichment_confidence')}"
        )
    print(f"\nUpdated {CSV_PATH}")


if __name__ == "__main__":
    main()
