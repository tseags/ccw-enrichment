#!/usr/bin/env python3
"""Fill missing vendor website URLs using Google search + Claude ranking."""

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
from urllib.parse import urlparse

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

logger = logging.getLogger(__name__)

SERPER_ENDPOINT = "https://google.serper.dev/search"
SERPER_CONCURRENCY = 5
CLAUDE_CONCURRENCY = 2
SERPER_TIMEOUT = 20
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 250
CLAUDE_MAX_RETRIES = 6
CLAUDE_BASE_BACKOFF_SECONDS = 2.0

BLOCKLIST_BASE_DOMAINS = {
    "facebook.com",
    "fb.com",
    "yelp.com",
    "yellowpages.com",
    "whitepages.com",
    "bbb.org",
    "mapquest.com",
    "google.com",
    "goo.gl",
    "linkedin.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "nextdoor.com",
    "tripadvisor.com",
    "manta.com",
    "chamberofcommerce.com",
}


@dataclass
class LookupResult:
    row_index: int
    vendor_name: str
    county: str
    status: str  # "found" | "not_found" | "error"
    url: str | None
    reason: str


def _normalize_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if not parsed.scheme:
        value = f"https://{value}"
    return value


def _extract_host(url: str) -> str:
    host = urlparse(url).netloc.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0]


def _is_blocklisted(host: str) -> bool:
    if not host:
        return True
    if host.endswith(".gov") or host == "gov":
        return True
    return any(host == d or host.endswith(f".{d}") for d in BLOCKLIST_BASE_DOMAINS)


def _build_query(row: dict[str, str]) -> str:
    vendor = (row.get("vendor_name") or "").strip()
    city = (row.get("city") or "").strip()
    state = (row.get("state") or "").strip() or "CA"
    phone = (row.get("phone") or "").strip()

    parts = [f'"{vendor}"', "CCW training"]
    if city:
        parts.append(city)
    parts.append(state)
    if phone:
        parts.append(phone)
    return " ".join(parts)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _search_serper_sync(api_key: str, query: str) -> list[dict[str, str]]:
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": 5}
    resp = requests.post(SERPER_ENDPOINT, headers=headers, json=payload, timeout=SERPER_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    organic = data.get("organic") or []
    results: list[dict[str, str]] = []
    for item in organic[:5]:
        link = (item.get("link") or "").strip()
        if not link:
            continue
        results.append(
            {
                "title": _clean_text(item.get("title") or ""),
                "url": link,
                "snippet": _clean_text(item.get("snippet") or ""),
            }
        )
    return results


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


def _choose_with_claude_sync(
    client: anthropic.Anthropic,
    vendor_name: str,
    county: str,
    city: str,
    state: str,
    phone: str,
    email: str,
    candidates: list[dict[str, str]],
) -> tuple[str | None, str]:
    result_lines = []
    for idx, item in enumerate(candidates, 1):
        result_lines.append(
            f"{idx}. title: {item['title']}\n"
            f"   url: {item['url']}\n"
            f"   snippet: {item['snippet']}"
        )
    results_text = "\n".join(result_lines)

    user_prompt = (
        "You are matching a business to its official website.\n"
        "Return ONLY JSON in this exact shape:\n"
        '{"url": string|null, "reason": string}\n\n'
        "Select only if you are reasonably confident it is the vendor's own site.\n"
        "Prefer official domains over directories, social pages, government pages, and aggregators.\n\n"
        f"Vendor:\n"
        f"- name: {vendor_name}\n"
        f"- county: {county}\n"
        f"- city: {city}\n"
        f"- state: {state}\n"
        f"- phone: {phone}\n"
        f"- email: {email}\n\n"
        "Candidate search results:\n"
        f"{results_text}"
    )

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = response.content[0].text if response.content else "{}"
    data = _extract_json_obj(text)
    url_val = data.get("url")
    reason_val = _clean_text(str(data.get("reason") or ""))
    if url_val is None:
        return None, reason_val or "Claude returned url=null"
    if not isinstance(url_val, str):
        return None, "Claude returned non-string url"
    chosen = _normalize_url(url_val)
    if not chosen:
        return None, "Claude returned empty url"
    return chosen, reason_val or "selected by Claude"


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
    email = (row.get("email") or "").strip()

    query = _build_query(row)
    loop = asyncio.get_running_loop()

    try:
        async with serper_sem:
            organic = await loop.run_in_executor(None, _search_serper_sync, serper_key, query)
    except Exception as exc:
        return LookupResult(
            row_index=row_index,
            vendor_name=vendor_name,
            county=county,
            status="error",
            url=None,
            reason=f"Serper error: {exc}",
        )

    filtered: list[dict[str, str]] = []
    removed = 0
    for item in organic:
        host = _extract_host(item["url"])
        if _is_blocklisted(host):
            removed += 1
            continue
        filtered.append(item)

    if not filtered:
        reason = "No candidates after filtering"
        if removed:
            reason += f" ({removed} blocked)"
        return LookupResult(
            row_index=row_index,
            vendor_name=vendor_name,
            county=county,
            status="not_found",
            url=None,
            reason=reason,
        )

    chosen_url: str | None = None
    reason = ""
    for attempt in range(CLAUDE_MAX_RETRIES + 1):
        try:
            async with claude_sem:
                chosen_url, reason = await loop.run_in_executor(
                    None,
                    _choose_with_claude_sync,
                    claude_client,
                    vendor_name,
                    county,
                    city,
                    state,
                    phone,
                    email,
                    filtered,
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
                url=None,
                reason=f"Claude error: {exc}",
            )

    if not chosen_url:
        return LookupResult(
            row_index=row_index,
            vendor_name=vendor_name,
            county=county,
            status="not_found",
            url=None,
            reason=reason or "Claude did not select a URL",
        )

    host = _extract_host(chosen_url)
    if _is_blocklisted(host):
        return LookupResult(
            row_index=row_index,
            vendor_name=vendor_name,
            county=county,
            status="not_found",
            url=None,
            reason="Claude selected blocked domain",
        )

    return LookupResult(
        row_index=row_index,
        vendor_name=vendor_name,
        county=county,
        status="found",
        url=chosen_url,
        reason=reason,
    )


def _load_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if "website_url" not in fieldnames:
        raise ValueError("Input CSV is missing required column: website_url")
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
        if (row.get("website_url") or "").strip():
            continue
        targets.append((idx, row))
        if limit is not None and len(targets) >= limit:
            break

    logger.info("Rows with blank website_url selected: %d", len(targets))
    if not targets:
        print("\nNo blank website_url rows to process.")
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
        if res.status == "found" and res.url:
            logger.info(
                "[%s] %s -> found %s (reason: %s)",
                res.county or "unknown",
                res.vendor_name or "(missing vendor_name)",
                res.url,
                res.reason,
            )
            found_updates.append((res.vendor_name, res.county, res.url))
            if not dry_run:
                rows[res.row_index]["website_url"] = res.url
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
                "[%s] %s -> not_found (reason: %s)",
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
    sample = found_updates[:10]

    print(f"\n{'-' * 64}")
    print("Website lookup summary")
    print(f"- Total vendors searched: {total}")
    print(f"- Websites found & added: {found_count}")
    print(f"- Not found (no good result): {not_found}")
    print(f"- Errors (API failures, etc.): {errors}")
    print("\nSample updates (up to 10):")
    if not sample:
        print("- (none)")
    else:
        for vendor_name, county, url in sample:
            print(f"- {vendor_name} | {county} | {url}")
    print(f"{'-' * 64}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lookup missing website_url values in enriched vendor CSV using Serper + Claude.",
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
        help="Only process the first N blank website_url rows.",
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
