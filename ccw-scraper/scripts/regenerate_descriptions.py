#!/usr/bin/env python3
"""
Regenerate low-uniqueness vendor_description fields for non-indexed profiles.

Default: --dry-run (writes audit outputs only).
Use --apply to update data/enriched/all-vendors.csv after review.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

# Allow imports from ccw-scraper root
_SCRAPER = Path(__file__).resolve().parents[1]
if str(_SCRAPER) not in sys.path:
    sys.path.insert(0, str(_SCRAPER))

from enrich.enricher import (  # noqa: E402
    Crawler,
    DOMAIN_DELAY,
    FALLBACK_PATHS,
    LINK_KEYWORDS,
    MAX_EXTRA_PAGES,
    TEXT_CHAR_LIMIT,
    _domain,
    _extract_text,
    _find_extra_links,
    _is_usable_http_url,
)
from scripts.gsc_profile_utils import (  # noqa: E402
    AUDIT_DIR,
    CSV_PATH,
    dedupe_vendors,
    eligible_for_regeneration,
    load_corpus_rows,
    load_discovered_not_indexed_urls,
    load_indexed_urls,
    normalize_gsc_url,
)

import anthropic

logger = logging.getLogger(__name__)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")

CHECKPOINT_PATH = AUDIT_DIR / "regeneration-checkpoint.json"
SCORES_PATH = AUDIT_DIR / "description-uniqueness-scores.csv"
OPENING_HISTORY_SIZE = 40
CHECKPOINT_EVERY = 50

DESCRIPTION_SYSTEM_PROMPT = """You write unique instructor profile "About" copy for a California CCW training directory.

Return ONLY valid JSON:
{
  "vendor_description": "string",
  "facts_used": ["list of specific facts drawn from source"],
  "insufficient_source_data": false
}

Content rules:
- Third person, plain direct marketing copy
- Minimum 100 words ONLY if source data supports it; target 150-250 when rich source exists
- Shorter genuine copy beats padded filler
- Vary sentence structure and opening phrasing — do NOT start with patterns like "X is a firearms training company" if forbidden
- Pull distinguishing facts ONLY when present in source: years in business, certifications (NRA/DOJ/USCCA/BSIS), named instructors, cities/counties served, specialty offerings, range partnerships, verified pricing
- Do NOT use generic filler ("comprehensive training", "decades of experience") unless source explicitly supports it
- Never fabricate certifications, claims, or facts
- Set insufficient_source_data: true if source cannot support a genuinely unique 100+ word description without fabrication"""


def _load_scores() -> dict[str, dict[str, str]]:
    if not SCORES_PATH.exists():
        raise FileNotFoundError(
            f"Run audit_description_uniqueness.py first ({SCORES_PATH} missing)"
        )
    out: dict[str, dict[str, str]] = {}
    with SCORES_PATH.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = row["normalized_vendor_name"].strip().lower()
            out[key] = row
    return out


def _structured_context(rows: list[dict[str, str]]) -> str:
    counties = sorted({r.get("county", "") for r in rows if r.get("county")})
    primary = rows[0]
    fields = {
        "vendor_name": primary.get("vendor_name", ""),
        "instructor_names": "; ".join(
            sorted({r.get("instructor_names", "") for r in rows if r.get("instructor_names")})
        ),
        "counties_served": ", ".join(counties),
        "cities": "; ".join(sorted({r.get("city", "") for r in rows if r.get("city")})),
        "state": primary.get("state", "CA"),
        "addresses": "; ".join(sorted({r.get("address", "") for r in rows if r.get("address")})),
        "phone": "; ".join(sorted({r.get("phone", "") for r in rows if r.get("phone")})),
        "email": "; ".join(sorted({r.get("email", "") for r in rows if r.get("email")})),
        "website_url": primary.get("website_url", ""),
        "booking_capability": primary.get("booking_capability", ""),
        "price_16hr_full": primary.get("price_16hr_full", ""),
        "price_8hr_renewal": primary.get("price_8hr_renewal", ""),
        "price_add_a_gun": primary.get("price_add_a_gun", ""),
        "crawl_status": primary.get("crawl_status", ""),
        "enrichment_confidence": primary.get("enrichment_confidence", ""),
        "confidence_notes": primary.get("confidence_notes", ""),
        "existing_description": primary.get("vendor_description", ""),
    }
    lines = ["Structured vendor data (ground truth — do not invent beyond this):"]
    for k, v in fields.items():
        if v:
            lines.append(f"- {k}: {v}")
    return "\n".join(lines)


async def _crawl_about_priority(crawler: Crawler, website_url: str) -> tuple[str, str]:
    """Re-crawl with /about prioritized. Returns (text, status)."""
    base = website_url.rstrip("/")
    all_htmls: list[str] = []
    all_texts: list[str] = []

    about_url = base + "/about"
    resp = await crawler.fetch(about_url)
    if resp is not None:
        all_htmls.append(resp.text)
        all_texts.append(_extract_text(resp.text))

    resp = await crawler.fetch(website_url)
    if resp is not None:
        all_htmls.append(resp.text)
        all_texts.append(_extract_text(resp.text))
        homepage = resp.text
        has_pricing = bool(re.search(r"\$\s?\d", homepage))
        if not has_pricing:
            extra_links = _find_extra_links(homepage, website_url)[:MAX_EXTRA_PAGES]
            for link in extra_links:
                r2 = await crawler.fetch(link)
                if r2 is not None:
                    all_htmls.append(r2.text)
                    all_texts.append(_extract_text(r2.text))
    elif not all_texts:
        for path in FALLBACK_PATHS:
            if path == "/about":
                continue
            fallback = base + path
            r3 = await crawler.fetch(fallback)
            if r3 is not None:
                all_htmls.append(r3.text)
                all_texts.append(_extract_text(r3.text))
                break

    if not all_texts:
        return "", "failed"

    combined = "\n\n---\n\n".join(all_texts)
    return combined[:TEXT_CHAR_LIMIT], "success"


def _opening_words(text: str, n: int = 8) -> str:
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    if not sents:
        return ""
    return " ".join(sents[0].lower().split()[:n])


def _call_claude_description(
    client: anthropic.Anthropic,
    vendor_name: str,
    context: str,
    page_text: str,
    forbidden_openings: list[str],
) -> dict[str, Any]:
    forbidden_block = ""
    if forbidden_openings:
        forbidden_block = (
            "\n\nDo NOT reuse these opening patterns already used in this batch:\n"
            + "\n".join(f"- {o}" for o in forbidden_openings[-OPENING_HISTORY_SIZE:])
        )

    user_msg = (
        f"Vendor: {vendor_name}\n\n{context}\n\n"
        f"--- Website content ---\n{page_text or '(no crawl text — use structured fields only)'}"
        f"{forbidden_block}"
    )

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1200,
        system=DESCRIPTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


async def _regenerate_vendor(
    client: anthropic.Anthropic,
    crawler: Crawler,
    vendor_key: str,
    county_rows: list[dict[str, str]],
    score_row: dict[str, str],
    forbidden_openings: list[str],
) -> dict[str, Any]:
    primary = county_rows[0]
    vendor_name = primary.get("vendor_name", vendor_key)
    context = _structured_context(county_rows)

    page_text = ""
    crawl_status = primary.get("crawl_status", "")
    website = (primary.get("website_url") or "").strip()
    if crawl_status == "success" and website and _is_usable_http_url(website):
        page_text, crawl_status = await _crawl_about_priority(crawler, website)
    elif website and _is_usable_http_url(website):
        page_text, crawl_status = await _crawl_about_priority(crawler, website)

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        _call_claude_description,
        client,
        vendor_name,
        context,
        page_text,
        forbidden_openings,
    )

    return {
        "normalized_vendor_name": vendor_key,
        "vendor_name": vendor_name,
        "profile_url": score_row.get("profile_url", ""),
        "gsc_status": score_row.get("gsc_status", ""),
        "uniqueness_score": score_row.get("uniqueness_score_1_5", ""),
        "old_description": primary.get("vendor_description", ""),
        "new_description": result.get("vendor_description", ""),
        "facts_used": result.get("facts_used", []),
        "insufficient_source_data": bool(result.get("insufficient_source_data")),
        "crawl_status": crawl_status,
        "county_rows_updated": len(county_rows),
    }


def _load_checkpoint() -> set[str]:
    if not CHECKPOINT_PATH.exists():
        return set()
    data = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return set(data.get("completed", []))


def _save_checkpoint(completed: set[str], results: list[dict]) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(
        json.dumps({
            "completed": sorted(completed),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "result_count": len(results),
        }, indent=2),
        encoding="utf-8",
    )


def _assert_no_indexed_overlap(results: list[dict], indexed_urls: set[str]) -> None:
    overlaps = []
    for r in results:
        url = normalize_gsc_url(r.get("profile_url", ""))
        if url in indexed_urls:
            overlaps.append(url)
    if overlaps:
        raise RuntimeError(
            f"SAFETY ABORT: {len(overlaps)} indexed URLs would be modified: {overlaps[:5]}"
        )


def _apply_to_csv(results: list[dict], county_map: dict[str, list[dict]]) -> int:
    """Update all county rows per vendor in all-vendors.csv."""
    changes = {r["normalized_vendor_name"]: r for r in results if not r.get("insufficient_source_data")}
    if not changes:
        return 0

    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    updated = 0
    for row in rows:
        key = (row.get("vendor_name") or "").strip().lower()
        if key not in changes:
            continue
        ch = changes[key]
        new_desc = (ch.get("new_description") or "").strip()
        if not new_desc:
            continue
        row["vendor_description"] = new_desc
        row["enriched_at"] = now
        facts = ch.get("facts_used") or []
        note = "description_regenerated_2026-07"
        if facts:
            note += "; facts: " + "; ".join(str(f) for f in facts[:8])
        existing = (row.get("confidence_notes") or "").strip()
        row["confidence_notes"] = f"{existing}; {note}".strip("; ").strip() if existing else note
        updated += 1

    backup = CSV_PATH.with_name("all-vendors.backup-before-description-regen.csv")
    if not backup.exists():
        backup.write_bytes(CSV_PATH.read_bytes())

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return updated


def _write_batch_stats(results: list[dict], skipped_indexed: int, skipped_score: int) -> None:
    openings = [_opening_words(r.get("new_description", "")) for r in results if r.get("new_description")]
    opening_counts = Counter(openings)
    total = len(openings) or 1
    top_opening, top_count = opening_counts.most_common(1)[0] if opening_counts else ("", 0)
    top_pct = round(100 * top_count / total, 1)

    insufficient = sum(1 for r in results if r.get("insufficient_source_data"))
    regenerated = sum(1 for r in results if r.get("new_description") and not r.get("insufficient_source_data"))

    lines = [
        "# Description regeneration batch stats",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"- Vendors processed: **{len(results)}**",
        f"- Descriptions regenerated: **{regenerated}**",
        f"- Insufficient source flagged: **{insufficient}**",
        f"- Skipped (indexed): **{skipped_indexed}**",
        f"- Skipped (score >3): **{skipped_score}**",
        "",
        "## Opening template distribution (new batch)",
        "",
        f"- Most common opening ({top_pct}%): `{top_opening}`",
        f"- Target: no single opening >15% — **{'PASS' if top_pct <= 15 else 'FAIL'}**",
        "",
        "### Top openings",
        "",
    ]
    for opening, cnt in opening_counts.most_common(15):
        pct = round(100 * cnt / total, 1)
        lines.append(f"- ({pct}%) `{opening}`")

    path = AUDIT_DIR / "regeneration-batch-stats.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {path}")


async def run_regeneration(
    dry_run: bool = True,
    limit: int | None = None,
    resume: bool = True,
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    indexed_urls = load_indexed_urls()
    discovered_urls = load_discovered_not_indexed_urls()
    scores = _load_scores()

    rows = load_corpus_rows(prefer_supabase=False)
    _, county_map = dedupe_vendors(rows)

    targets: list[tuple[str, dict, list[dict]]] = []
    skipped_indexed = 0
    skipped_score = 0
    for key, group in county_map.items():
        score_row = scores.get(key)
        if not score_row:
            continue
        score = int(score_row.get("uniqueness_score_1_5", 5))
        profile_url = score_row.get("profile_url", "")
        if not eligible_for_regeneration(score, profile_url, indexed_urls, discovered_urls):
            if score <= 3 and normalize_gsc_url(profile_url) in indexed_urls:
                skipped_indexed += 1
            elif score > 3:
                skipped_score += 1
            elif discovered_urls is not None:
                skipped_score += 1
            continue
        targets.append((key, score_row, group))

    targets.sort(key=lambda t: (int(t[1].get("uniqueness_score_1_5", 5)), -float(t[1].get("nearest_neighbor_similarity", 0))))
    if limit:
        targets = targets[:limit]

    print(f"Regeneration targets: {len(targets)} (skipped indexed={skipped_indexed}, score>3={skipped_score})")

    completed = _load_checkpoint() if resume else set()
    prior_results_path = AUDIT_DIR / "regenerated-descriptions.json"
    results: list[dict] = []
    if resume and prior_results_path.exists():
        results = json.loads(prior_results_path.read_text(encoding="utf-8"))

    try:
        from dotenv import load_dotenv
        load_dotenv(_SCRAPER / ".env")
        load_dotenv(_SCRAPER.parent / ".env.local")
    except ImportError:
        pass

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in ccw-scraper/.env")

    client = anthropic.Anthropic(api_key=api_key)
    crawler = Crawler()
    forbidden_openings: list[str] = [
        _opening_words(r.get("new_description", ""))
        for r in results
        if r.get("new_description")
    ]

    for i, (key, score_row, group) in enumerate(targets, 1):
        if key in completed:
            continue
        logger.info("[%d/%d] Regenerating %s", i, len(targets), group[0].get("vendor_name", key))
        try:
            result = await _regenerate_vendor(
                client, crawler, key, group, score_row, forbidden_openings
            )
            results.append(result)
            if result.get("new_description") and not result.get("insufficient_source_data"):
                forbidden_openings.append(_opening_words(result["new_description"]))
            completed.add(key)
        except Exception as exc:
            logger.error("Failed %s: %s", key, exc)
            results.append({
                "normalized_vendor_name": key,
                "vendor_name": group[0].get("vendor_name", ""),
                "profile_url": score_row.get("profile_url", ""),
                "error": str(exc),
            })

        if i % CHECKPOINT_EVERY == 0:
            _save_checkpoint(completed, results)
            prior_results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
            logger.info("Checkpoint at %d vendors", i)

    _save_checkpoint(completed, results)
    prior_results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # CSV outputs
    regen_csv = AUDIT_DIR / "regenerated-descriptions.csv"
    csv_fields = [
        "normalized_vendor_name", "vendor_name", "profile_url", "gsc_status",
        "uniqueness_score", "insufficient_source_data", "county_rows_updated",
        "facts_used", "old_description", "new_description",
    ]
    with regen_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        w.writeheader()
        for r in results:
            row = dict(r)
            if isinstance(row.get("facts_used"), list):
                row["facts_used"] = "; ".join(str(x) for x in row["facts_used"])
            w.writerow(row)
    print(f"Wrote {regen_csv}")

    insufficient_rows = [r for r in results if r.get("insufficient_source_data")]
    insuff_path = AUDIT_DIR / "insufficient-source-flagged.csv"
    with insuff_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        w.writeheader()
        for r in insufficient_rows:
            row = dict(r)
            if isinstance(row.get("facts_used"), list):
                row["facts_used"] = "; ".join(str(x) for x in row["facts_used"])
            w.writerow(row)
    print(f"Wrote {insuff_path} ({len(insufficient_rows)} flagged)")

    _write_batch_stats(results, skipped_indexed, skipped_score)

    valid_results = [r for r in results if r.get("new_description") and not r.get("insufficient_source_data")]
    _assert_no_indexed_overlap(valid_results, indexed_urls)

    if dry_run:
        print("DRY RUN — no CSV changes. Review regenerated-descriptions.csv then run with --apply")
    else:
        n = _apply_to_csv(valid_results, county_map)
        print(f"APPLIED — updated {n} county rows in {CSV_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate low-uniqueness vendor descriptions")
    parser.add_argument("--apply", action="store_true", help="Write changes to all-vendors.csv")
    parser.add_argument("--limit", type=int, default=None, help="Process only N vendors (for testing)")
    parser.add_argument("--no-resume", action="store_true", help="Ignore checkpoint")
    args = parser.parse_args()
    asyncio.run(run_regeneration(dry_run=not args.apply, limit=args.limit, resume=not args.no_resume))


if __name__ == "__main__":
    main()
