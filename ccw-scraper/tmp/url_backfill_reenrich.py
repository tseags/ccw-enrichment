#!/usr/bin/env python3
"""
Re-run web enrichment for vendors that had no website_url in the baseline snapshot
(tmp/backfill-before/all-vendors.before.csv) but have a URL in data/all-vendors.csv now.

Baseline rationale: those rows were enriched as crawl_status=no_website (no usable URL
at the time). After URL backfill, they need a targeted re-crawl.

Usage (from ccw-scraper/):
  .venv/bin/python tmp/url_backfill_reenrich.py build
  .venv/bin/python run_enrich.py --all-counties --input tmp/enrich-backfill-subset.csv \\
      --output tmp/enrich-backfill-subset.out.csv
  .venv/bin/python tmp/url_backfill_reenrich.py merge
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enrich.enricher import OUTPUT_COLUMNS  # noqa: E402

BASELINE_CSV = ROOT / "tmp/backfill-before/all-vendors.before.csv"
SHORT_CSV = ROOT / "data/all-vendors.csv"
MASTER_CSV = ROOT / "data/enriched/all-vendors.csv"
SUBSET_CSV = ROOT / "tmp/enrich-backfill-subset.csv"
SUBSET_OUT_CSV = ROOT / "tmp/enrich-backfill-subset.out.csv"
REPORT_PATH = ROOT / "tmp/url-backfill-report.txt"


def norm_name(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[.,]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def stable_key(county: str, vendor_name: str) -> tuple[str, str]:
    return (county.strip().lower(), norm_name(vendor_name))


def _domain(url: str) -> str:
    return urlparse(url.strip()).netloc.lower().replace("www.", "")


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def gained_url_rows(
    before: list[dict[str, str]], current: list[dict[str, str]]
) -> list[tuple[str, str, str, str]]:
    """(county, norm_short_name, display_short_name, new_url) for vendors that gained a URL."""
    bmap = {
        (r["county"].strip().lower(), norm_name(r["vendor_name"])): r for r in before
    }
    out: list[tuple[str, str, str, str]] = []
    for r in current:
        k = (r["county"].strip().lower(), norm_name(r["vendor_name"]))
        cu = (r.get("website_url") or "").strip()
        if not cu:
            continue
        brow = bmap.get(k)
        bu = (brow.get("website_url") or "").strip() if brow else ""
        if not bu:
            out.append((k[0], k[1], r["vendor_name"], cu))
    return out


def match_enriched_row(
    county: str,
    norm_short: str,
    new_url: str,
    by_county: dict[str, list[dict[str, str]]],
) -> tuple[dict[str, str] | None, str | None]:
    lst = by_county.get(county.strip().lower(), [])
    exact = [er for er in lst if norm_name(er["vendor_name"]) == norm_short]
    if len(exact) == 1:
        return exact[0], None
    if len(exact) > 1:
        return None, "duplicate_exact"
    prefix = [
        er
        for er in lst
        if norm_name(er["vendor_name"]).startswith(norm_short + " ")
    ]
    if len(prefix) == 1:
        return prefix[0], None
    if len(prefix) > 1:
        return None, "ambiguous_prefix"
    # Same county + same site hostname (renamed vendor on source list)
    dom = _domain(new_url)
    if dom:
        dom_hits = [
            er
            for er in lst
            if _domain(er.get("website_url") or "") == dom
        ]
        if len(dom_hits) == 1:
            return dom_hits[0], None
        if len(dom_hits) > 1:
            return None, "ambiguous_domain"
    return None, "no_match"


def invalid_url(url: str) -> bool:
    u = url.lower().strip()
    if not u:
        return True
    if "no website" in u:
        return True
    if u in ("n/a", "none", "tbd", "n/a."):
        return True
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return True
    host = parsed.netloc.split("@")[-1].split(":")[0]
    if not host or any(c in host for c in " \t\n\r"):
        return True
    return False


def build_subset() -> tuple[list[dict[str, str]], list[str]]:
    before = load_rows(BASELINE_CSV)
    current = load_rows(SHORT_CSV)
    enriched = load_rows(MASTER_CSV)
    by_county: dict[str, list[dict[str, str]]] = {}
    for er in enriched:
        c = er["county"].strip().lower()
        by_county.setdefault(c, []).append(er)

    gained = gained_url_rows(before, current)
    subset_rows: list[dict[str, str]] = []
    notes: list[str] = []
    for county, norm_s, disp_s, url in gained:
        if invalid_url(url):
            notes.append(f"skip_invalid_url: {county} | {disp_s} | {url!r}")
            continue
        er, err = match_enriched_row(county, norm_s, url, by_county)
        if err:
            notes.append(f"match_fail:{err}: {county} | {disp_s} | {url}")
            continue
        assert er is not None
        row = {col: (er.get(col) or "") for col in OUTPUT_COLUMNS}
        row["website_url"] = url.strip()
        subset_rows.append(row)

    SUBSET_CSV.parent.mkdir(parents=True, exist_ok=True)
    with SUBSET_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(subset_rows)

    notes.insert(0, f"subset_rows_written={len(subset_rows)} path={SUBSET_CSV}")
    return subset_rows, notes


def merge_master() -> tuple[list[str], dict[str, int]]:
    if not SUBSET_OUT_CSV.exists():
        raise SystemExit(f"Missing {SUBSET_OUT_CSV}; run enrichment first.")

    # run_enrich.py uses output_path.parent as image root, so subset runs write to tmp/images/.
    # Copy only vendor slug subdirs under each county — never replace the whole county folder.
    tmp_img = ROOT / "tmp" / "images"
    dest_img = ROOT / "data" / "enriched" / "images"
    if tmp_img.is_dir():
        dest_img.mkdir(parents=True, exist_ok=True)
        for county_dir in tmp_img.iterdir():
            if not county_dir.is_dir():
                continue
            dest_county = dest_img / county_dir.name
            dest_county.mkdir(parents=True, exist_ok=True)
            for slug_dir in county_dir.iterdir():
                if not slug_dir.is_dir():
                    continue
                target = dest_county / slug_dir.name
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(slug_dir, target)

    updates = load_rows(SUBSET_OUT_CSV)
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    conflicts: list[str] = []
    for r in updates:
        k = stable_key(r["county"], r["vendor_name"])
        if k in by_key:
            conflicts.append(f"duplicate_subset_key: {k!r}")
        by_key[k] = r

    master = load_rows(MASTER_CSV)
    replaced = 0
    missing: list[str] = []
    new_lines: list[dict[str, str]] = []
    for r in master:
        k = stable_key(r["county"], r["vendor_name"])
        if k in by_key:
            new_lines.append(by_key[k])
            replaced += 1
            del by_key[k]
        else:
            new_lines.append(r)

    for k in sorted(by_key.keys()):
        missing.append(f"subset_key_not_in_master: {k!r}")

    with MASTER_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(new_lines)

    stats = {
        "replaced": replaced,
        "subset_unmatched": len(missing),
        "conflicts": len(conflicts),
    }
    report_lines = [
        f"merge: replaced_rows={replaced}",
        f"merge: subset_keys_not_found_in_master={len(missing)}",
        f"merge: duplicate_keys_in_subset={len(conflicts)}",
    ]
    report_lines.extend(conflicts)
    report_lines.extend(missing)
    return report_lines, stats


def summarize_out() -> dict[str, int]:
    rows = load_rows(SUBSET_OUT_CSV)
    n = len(rows)
    return {
        "n": n,
        "success": sum(1 for r in rows if r.get("crawl_status") == "success"),
        "failed": sum(1 for r in rows if r.get("crawl_status") == "failed"),
        "no_website": sum(1 for r in rows if r.get("crawl_status") == "no_website"),
        "parse_error": sum(1 for r in rows if r.get("crawl_status") == "parse_error"),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["build", "merge", "report"])
    args = p.parse_args()

    if args.command == "build":
        _, notes = build_subset()
        for line in notes:
            print(line)
    elif args.command == "merge":
        lines, stats = merge_master()
        for line in lines:
            print(line)
        summ = summarize_out()
        failed_vendors = [
            f'{r["county"]} | {r["vendor_name"]} | {r.get("crawl_status")} | {r.get("website_url", "")[:60]}'
            for r in load_rows(SUBSET_OUT_CSV)
            if r.get("crawl_status") in ("failed", "parse_error", "no_website")
        ]
        report = [
            "URL backfill re-enrichment",
            f"target_subset_size={summ['n']}",
            f"crawl_success={summ['success']}",
            f"crawl_failed={summ['failed']}",
            f"crawl_no_website={summ['no_website']}",
            f"crawl_parse_error={summ['parse_error']}",
            f"merge_replaced={stats['replaced']}",
            "",
            "Still failing after retry:",
            *failed_vendors,
        ]
        REPORT_PATH.write_text("\n".join(report) + "\n", encoding="utf-8")
        print(f"Wrote {REPORT_PATH}")
    else:
        if not SUBSET_OUT_CSV.exists():
            print("No subset output yet.")
            return
        print(summarize_out())


if __name__ == "__main__":
    main()
