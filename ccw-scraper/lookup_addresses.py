#!/usr/bin/env python3
"""Fill missing vendor street addresses using Serper search + places + Claude verification."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

logger = logging.getLogger(__name__)

SERPER_SEARCH_ENDPOINT = "https://google.serper.dev/search"
SERPER_PLACES_ENDPOINT = "https://google.serper.dev/places"
SERPER_CONCURRENCY = 5
CLAUDE_CONCURRENCY = 2
SERPER_TIMEOUT = 20
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 350
CLAUDE_MAX_RETRIES = 6
CLAUDE_BASE_BACKOFF_SECONDS = 2.0


@dataclass
class LookupResult:
    row_index: int
    vendor_name: str
    county: str
    status: str  # "found" | "not_found" | "error"
    address: str | None
    reason: str


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _build_search_query(row: dict[str, str]) -> str:
    vendor = (row.get("vendor_name") or "").strip()
    city = (row.get("city") or "").strip()
    state = (row.get("state") or "").strip() or "CA"
    parts = [f'"{vendor}"', "address"]
    if city:
        parts.append(city)
    parts.append(state)
    return " ".join(parts)


def _build_places_query(row: dict[str, str]) -> str:
    vendor = (row.get("vendor_name") or "").strip()
    city = (row.get("city") or "").strip()
    state = (row.get("state") or "").strip() or "CA"
    parts = [vendor]
    if city:
        parts.append(city)
    parts.append(state)
    return " ".join(parts)


def _search_serper_sync(api_key: str, query: str, endpoint: str) -> dict[str, Any]:
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    payload: dict[str, Any] = {"q": query}
    if endpoint == SERPER_SEARCH_ENDPOINT:
        payload["num"] = 5
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=SERPER_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _extract_candidate_addresses(
    search_data: dict[str, Any],
    places_data: dict[str, Any],
) -> list[dict[str, str]]:
    """Pull candidate addresses from knowledgeGraph and places results."""
    candidates: list[dict[str, str]] = []

    kg = search_data.get("knowledgeGraph") or {}
    if kg.get("address"):
        candidates.append({
            "source": "knowledgeGraph",
            "name": _clean_text(kg.get("title") or ""),
            "address": _clean_text(kg.get("address") or ""),
            "phone": _clean_text(kg.get("phone") or ""),
            "description": _clean_text(kg.get("description") or ""),
        })

    for place in (places_data.get("places") or [])[:5]:
        addr = _clean_text(place.get("address") or "")
        if not addr:
            continue
        candidates.append({
            "source": "places",
            "name": _clean_text(place.get("title") or ""),
            "address": addr,
            "phone": _clean_text(place.get("phoneNumber") or ""),
            "description": _clean_text(place.get("category") or ""),
        })

    # Also check organic results for address-like snippets in knowledgeGraph
    # that might have been missed — but the main sources are above.
    return candidates


def _extract_json_obj(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        raise json.JSONDecodeError("No JSON object found", raw, 0)
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise json.JSONDecodeError("Top-level JSON is not an object", raw, 0)
    return data


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "rate_limit_error" in msg
        or "too many requests" in msg
        or " 429 " in msg
        or "error code: 429" in msg
        or "would exceed your organization's rate limit" in msg
    )


def _verify_with_claude_sync(
    client: anthropic.Anthropic,
    vendor_name: str,
    county: str,
    city: str,
    state: str,
    phone: str,
    candidates: list[dict[str, str]],
) -> tuple[str | None, str]:
    candidate_lines = []
    for idx, c in enumerate(candidates, 1):
        candidate_lines.append(
            f"{idx}. source: {c['source']}\n"
            f"   name: {c['name']}\n"
            f"   address: {c['address']}\n"
            f"   phone: {c['phone']}\n"
            f"   description: {c['description']}"
        )
    candidates_text = "\n".join(candidate_lines)

    user_prompt = (
        "You are verifying whether a candidate street address belongs to a specific business.\n"
        "Return ONLY JSON in this exact shape:\n"
        '{"address": string|null, "reason": string}\n\n'
        "Rules:\n"
        "- Select an address only if the candidate name is a fuzzy match for the vendor name\n"
        "  (e.g. abbreviations, slight spelling differences, or the vendor name appears as a\n"
        "  substring of the candidate name).\n"
        "- The candidate must be in the same general geographic area (same city, or nearby city\n"
        "  in the same county/state). A training company may list a range address in a nearby\n"
        "  town — that is acceptable.\n"
        "- If the phone numbers are provided and they match, that is strong confirmation.\n"
        "- If multiple candidates match, prefer the one from knowledgeGraph.\n"
        "- If none match well, return address=null.\n\n"
        f"Vendor:\n"
        f"- name: {vendor_name}\n"
        f"- county: {county}\n"
        f"- city: {city}\n"
        f"- state: {state}\n"
        f"- phone: {phone}\n\n"
        f"Candidate addresses:\n{candidates_text}"
    )

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = response.content[0].text if response.content else "{}"
    data = _extract_json_obj(text)
    addr_val = data.get("address")
    reason_val = _clean_text(str(data.get("reason") or ""))
    if addr_val is None:
        return None, reason_val or "Claude returned address=null"
    if not isinstance(addr_val, str):
        return None, "Claude returned non-string address"
    addr_val = _clean_text(addr_val)
    if not addr_val:
        return None, "Claude returned empty address"
    return addr_val, reason_val or "verified by Claude"


async def _lookup_one(
    row_index: int,
    row: dict[str, str],
    serper_key: str,
    claude_client: anthropic.Anthropic,
    serper_sem: asyncio.Semaphore,
    claude_sem: asyncio.Semaphore,
) -> LookupResult:
    vendor_name = (row.get("vendor_name") or "").strip()
    county = (row.get("county") or "").strip()
    city = (row.get("city") or "").strip()
    state = (row.get("state") or "").strip()
    phone = (row.get("phone") or "").strip()

    search_query = _build_search_query(row)
    places_query = _build_places_query(row)
    loop = asyncio.get_running_loop()

    search_data: dict[str, Any] = {}
    places_data: dict[str, Any] = {}

    try:
        async with serper_sem:
            search_data = await loop.run_in_executor(
                None, _search_serper_sync, serper_key, search_query, SERPER_SEARCH_ENDPOINT,
            )
            places_data = await loop.run_in_executor(
                None, _search_serper_sync, serper_key, places_query, SERPER_PLACES_ENDPOINT,
            )
    except Exception as exc:
        return LookupResult(
            row_index=row_index,
            vendor_name=vendor_name,
            county=county,
            status="error",
            address=None,
            reason=f"Serper error: {exc}",
        )

    candidates = _extract_candidate_addresses(search_data, places_data)
    if not candidates:
        return LookupResult(
            row_index=row_index,
            vendor_name=vendor_name,
            county=county,
            status="not_found",
            address=None,
            reason="No candidate addresses from search or places",
        )

    chosen_address: str | None = None
    reason = ""
    for attempt in range(CLAUDE_MAX_RETRIES + 1):
        try:
            async with claude_sem:
                chosen_address, reason = await loop.run_in_executor(
                    None,
                    _verify_with_claude_sync,
                    claude_client,
                    vendor_name,
                    county,
                    city,
                    state,
                    phone,
                    candidates,
                )
            break
        except Exception as exc:
            if _is_rate_limit_error(exc) and attempt < CLAUDE_MAX_RETRIES:
                backoff = CLAUDE_BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 0.75)
                logger.info(
                    "[%s] %s -> Claude rate-limited; retrying in %.2fs (attempt %d/%d)",
                    county or "unknown",
                    vendor_name or "(missing vendor_name)",
                    backoff,
                    attempt + 1,
                    CLAUDE_MAX_RETRIES,
                )
                await asyncio.sleep(backoff)
                continue
            return LookupResult(
                row_index=row_index,
                vendor_name=vendor_name,
                county=county,
                status="error",
                address=None,
                reason=f"Claude error: {exc}",
            )

    if not chosen_address:
        return LookupResult(
            row_index=row_index,
            vendor_name=vendor_name,
            county=county,
            status="not_found",
            address=None,
            reason=reason or "Claude did not verify any address",
        )

    return LookupResult(
        row_index=row_index,
        vendor_name=vendor_name,
        county=county,
        status="found",
        address=chosen_address,
        reason=reason,
    )


def _load_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if "address" not in fieldnames:
        raise ValueError("Input CSV is missing required column: address")
    return fieldnames, rows


def _write_rows(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


async def run_lookup(
    input_path: Path,
    output_path: Path,
    serper_key: str,
    anthropic_key: str,
    dry_run: bool,
    limit: int | None,
) -> None:
    fieldnames, rows = _load_rows(input_path)

    targets: list[tuple[int, dict[str, str]]] = []
    for idx, row in enumerate(rows):
        if (row.get("address") or "").strip():
            continue
        targets.append((idx, row))
        if limit is not None and len(targets) >= limit:
            break

    logger.info("Rows with blank address selected: %d", len(targets))
    if not targets:
        print("\nNo blank address rows to process.")
        return

    claude_client = anthropic.Anthropic(api_key=anthropic_key)
    serper_sem = asyncio.Semaphore(SERPER_CONCURRENCY)
    claude_sem = asyncio.Semaphore(CLAUDE_CONCURRENCY)

    tasks = [
        _lookup_one(i, row, serper_key, claude_client, serper_sem, claude_sem)
        for i, row in targets
    ]
    results = await asyncio.gather(*tasks)

    found_updates: list[tuple[str, str, str]] = []
    not_found = 0
    errors = 0

    for res in results:
        if res.status == "found" and res.address:
            logger.info(
                "[%s] %s -> found: %s (reason: %s)",
                res.county or "unknown",
                res.vendor_name or "(missing vendor_name)",
                res.address,
                res.reason,
            )
            found_updates.append((res.vendor_name, res.county, res.address))
            if not dry_run:
                rows[res.row_index]["address"] = res.address
        elif res.status == "not_found":
            logger.info(
                "[%s] %s -> not_found (reason: %s)",
                res.county or "unknown",
                res.vendor_name or "(missing vendor_name)",
                res.reason,
            )
            not_found += 1
        else:
            logger.info(
                "[%s] %s -> error (reason: %s)",
                res.county or "unknown",
                res.vendor_name or "(missing vendor_name)",
                res.reason,
            )
            errors += 1

    if dry_run:
        logger.info("Dry run enabled; no CSV changes written.")
    else:
        _write_rows(output_path, fieldnames, rows)
        logger.info("Wrote updated CSV to %s", output_path)

    total = len(results)
    found_count = len(found_updates)
    sample = found_updates[:15]

    print(f"\n{'-' * 72}")
    print("Address lookup summary")
    print(f"- Total vendors searched:  {total}")
    print(f"- Addresses found & added: {found_count}")
    print(f"- Not found (no match):    {not_found}")
    print(f"- Errors (API failures):   {errors}")
    print("\nUpdates (up to 15):")
    if not sample:
        print("  (none)")
    else:
        for vendor_name, county, address in sample:
            print(f"  {vendor_name} | {county} | {address}")
    print(f"{'-' * 72}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lookup missing street addresses in enriched vendor CSV using Serper + Claude.",
    )
    parser.add_argument(
        "--input",
        default="data/enriched/all-vendors.csv",
        help="Input CSV path (default: data/enriched/all-vendors.csv)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output CSV path (default: overwrite --input)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print would-be updates without writing the CSV.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N blank address rows.",
    )
    args = parser.parse_args()

    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be a positive integer")

    serper_key = os.environ.get("SERPER_API_KEY", "").strip()
    if not serper_key:
        raise SystemExit("SERPER_API_KEY not set. Add it to .env or export it.")

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not anthropic_key:
        raise SystemExit("ANTHROPIC_API_KEY not set. Add it to .env or export it.")

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input CSV not found: {input_path}")

    output_path = Path(args.output) if args.output else input_path

    asyncio.run(
        run_lookup(
            input_path=input_path,
            output_path=output_path,
            serper_key=serper_key,
            anthropic_key=anthropic_key,
            dry_run=args.dry_run,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    main()
