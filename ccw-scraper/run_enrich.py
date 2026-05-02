#!/usr/bin/env python3
"""CLI entrypoint for enriching CCW vendor data via web crawling + Claude."""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from enrich.enricher import (  # noqa: E402
    OUTPUT_COLUMNS,
    enrich_vendors,
    load_vendors,
    write_enriched_csv,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


KEY_REPORT_FIELDS = [
    "email",
    "address",
    "booking_capability",
    "price_16hr_day1",
    "price_16hr_day2",
    "price_16hr_full",
    "price_8hr_renewal",
    "price_8hr_initial",
    "price_add_a_gun",
    "vendor_description",
]


def _is_non_empty(value: object) -> bool:
    if value is None:
        return False
    return str(value).strip() != ""


def _load_rows_with_header(csv_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return rows, list(reader.fieldnames or OUTPUT_COLUMNS)


def _write_rows_with_header(rows: list[dict[str, str]], output_path: Path, header: list[str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _safe_merge_row(original: dict[str, str], enriched: dict[str, object], columns: list[str]) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    merged = dict(original)
    changes: dict[str, tuple[str, str]] = {}
    for col in columns:
        old = merged.get(col, "")
        new = enriched.get(col)
        if not _is_non_empty(new):
            continue
        new_str = str(new).strip()
        if new_str != str(old).strip():
            merged[col] = new_str
            changes[col] = (str(old), new_str)
    return merged, changes


def main() -> None:
    p = argparse.ArgumentParser(
        description="Enrich CCW vendor records by crawling websites.",
    )
    scope = p.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--county",
        metavar="SLUG",
        help="Filter to one county (e.g. marin). Only those rows are loaded from --input.",
    )
    scope.add_argument(
        "--all-counties",
        action="store_true",
        help=(
            "Process every row in --input in file order (all counties). "
            "Rows without website_url get crawl_status=no_website; rows with a URL are enriched. "
            "HTTP/Claude concurrency is global across the dataset."
        ),
    )
    p.add_argument(
        "--input",
        default="data/all-vendors.csv",
        help="Vendor CSV (default: data/all-vendors.csv)",
    )
    p.add_argument(
        "--output",
        nargs="?",
        default=None,
        help="Enriched CSV path. Required with --county; with --all-counties defaults to data/enriched/all-vendors.csv",
    )
    p.add_argument(
        "--newly-crawlable-only",
        action="store_true",
        help=(
            "Process only rows where website_url is present and crawl_status is exactly "
            "'no_website'. Merge non-empty enrichment improvements back into original rows."
        ),
    )
    args = p.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set. Add it to .env or export it.")

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"Input file not found: {input_path}")

    if args.all_counties:
        output_path = Path(args.output or "data/enriched/all-vendors.csv")
    else:
        if not args.output:
            sys.exit("--output is required when using --county")
        output_path = Path(args.output)

    output_dir = output_path.parent

    if args.newly_crawlable_only:
        if not args.all_counties:
            sys.exit("--newly-crawlable-only currently requires --all-counties")

        all_rows, header = _load_rows_with_header(input_path)
        if not all_rows:
            sys.exit(f"No rows in {input_path}")
        logger.info("Loaded %d vendors (all counties)", len(all_rows))

        match_indexes = [
            idx for idx, row in enumerate(all_rows)
            if _is_non_empty(row.get("website_url")) and (row.get("crawl_status") or "").strip() == "no_website"
        ]
        filtered_rows = [all_rows[i] for i in match_indexes]
        print(f"Strict filter matches: {len(filtered_rows)} rows")
        print("Sample matches (up to 10):")
        for row in filtered_rows[:10]:
            print(f"  - {row.get('vendor_name', '').strip()} | {row.get('county', '').strip()}")

        if not filtered_rows:
            print("No rows match filter; no enrichment run performed.")
            return

        before_snapshots = [dict(r) for r in filtered_rows]
        results = asyncio.run(enrich_vendors(filtered_rows, api_key, output_dir=output_dir))
        processed = len(results)

        changed_counts = {field: 0 for field in KEY_REPORT_FIELDS}
        changed_examples: list[dict[str, object]] = []
        status_counter: Counter[str] = Counter()
        remaining_errors: list[tuple[str, str, str]] = []

        for local_idx, enriched in enumerate(results):
            global_idx = match_indexes[local_idx]
            before_row = before_snapshots[local_idx]
            merged_row, changes = _safe_merge_row(all_rows[global_idx], enriched, header)
            all_rows[global_idx] = merged_row

            status = (merged_row.get("crawl_status") or "").strip() or "null"
            status_counter[status] += 1
            if status in {"failed", "parse_error", "no_website"}:
                reason = (merged_row.get("confidence_notes") or "").strip() or "missing/empty crawl or extraction output"
                remaining_errors.append((
                    merged_row.get("vendor_name", "").strip(),
                    merged_row.get("county", "").strip(),
                    f"{status}: {reason}",
                ))

            field_deltas: dict[str, tuple[str, str]] = {}
            for field in KEY_REPORT_FIELDS:
                before_val = (before_row.get(field) or "").strip()
                after_val = (merged_row.get(field) or "").strip()
                if not before_val and after_val:
                    changed_counts[field] += 1
                if before_val != after_val:
                    field_deltas[field] = (before_val, after_val)

            if field_deltas:
                changed_examples.append({
                    "vendor_name": merged_row.get("vendor_name", "").strip(),
                    "county": merged_row.get("county", "").strip(),
                    "fields": field_deltas,
                })

        _write_rows_with_header(all_rows, output_path, header)
        logger.info("Wrote %d rows to %s (updated %d filtered rows)", len(all_rows), output_path, processed)

        print(f"\nPost-run report")
        print(f"Rows matched by filter: {len(filtered_rows)}")
        print(f"Rows actually processed: {processed}")
        print("crawl_status distribution (processed rows):")
        for status, count in sorted(status_counter.items()):
            print(f"  - {status}: {count}")

        print("Newly populated key-field counts:")
        for field in KEY_REPORT_FIELDS:
            print(f"  - {field}: {changed_counts[field]}")

        print("10 before -> after examples:")
        for ex in changed_examples[:10]:
            print(f"  - {ex['vendor_name']} | {ex['county']}")
            for field, (before, after) in ex["fields"].items():
                print(f"      {field}: {before or '<empty>'} -> {after or '<empty>'}")
        if not changed_examples:
            print("  - No rows gained changed key fields.")

        print("Remaining errors:")
        if remaining_errors:
            for name, county, reason in remaining_errors[:25]:
                print(f"  - {name} | {county}: {reason}")
            if len(remaining_errors) > 25:
                print(f"  - ... and {len(remaining_errors) - 25} more")
        else:
            print("  - None")
        return

    if args.all_counties:
        rows = load_vendors(input_path, county=None)
        if not rows:
            sys.exit(f"No rows in {input_path}")
        logger.info("Loaded %d vendors (all counties)", len(rows))
    else:
        rows = load_vendors(input_path, county=args.county)
        if not rows:
            sys.exit(f"No vendors found for county={args.county!r} in {input_path}")
        logger.info("Loaded %d vendors for county=%s", len(rows), args.county)

    results = asyncio.run(enrich_vendors(rows, api_key, output_dir=output_dir))

    write_enriched_csv(results, output_path)
    logger.info("Wrote %d enriched records to %s", len(results), output_path)

    # Summary
    n = len(results)
    with_website = sum(1 for r in results if (r.get("website_url") or "").strip())
    success = sum(1 for r in results if r["crawl_status"] == "success")
    failed = sum(1 for r in results if r["crawl_status"] == "failed")
    no_web = sum(1 for r in results if r["crawl_status"] == "no_website")
    parse_err = sum(1 for r in results if r["crawl_status"] == "parse_error")

    print(f"\n{'─' * 60}")
    print(f"  Enrichment complete: {n} vendors ({with_website} with website_url, {n - with_website} without)")
    print(f"  ✓ success:     {success}")
    print(f"  ✗ failed:      {failed}")
    print(f"  – no_website:  {no_web}")
    print(f"  ? parse_error: {parse_err}")

    # Confidence
    conf = {}
    for r in results:
        c = r.get("enrichment_confidence") or "null"
        conf[c] = conf.get(c, 0) + 1
    print(f"\n  Confidence distribution:")
    for k in ("high", "medium", "low", "null"):
        if k in conf:
            print(f"    {k:20s} {conf[k]}")

    price_fields = [c for c in OUTPUT_COLUMNS if c.startswith("price_")]
    print(f"\n  Price field coverage:")
    for pf in price_fields:
        count = sum(1 for r in results if r.get(pf) is not None)
        print(f"    {pf:24s} {count}/{n}")

    booking = {}
    for r in results:
        bk = r.get("booking_capability") or "null"
        booking[bk] = booking.get(bk, 0) + 1
    print(f"\n  Booking capability:")
    for k, v in sorted(booking.items()):
        print(f"    {k:20s} {v}")

    # Image stats
    logos = sum(1 for r in results if r.get("logo_path"))
    instr = sum(1 for r in results if r.get("instructor_image_paths"))
    train = sum(1 for r in results if r.get("training_image_paths"))
    print(f"\n  Images downloaded:")
    print(f"    logos:               {logos}/{n}")
    print(f"    instructor photos:   {instr}/{n}")
    print(f"    training photos:     {train}/{n}")
    print(f"{'─' * 60}\n")


if __name__ == "__main__":
    main()
