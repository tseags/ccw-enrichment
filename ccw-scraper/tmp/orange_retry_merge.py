#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
import shutil
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CSV = ROOT / "data" / "all-vendors.csv"
MASTER_CSV = ROOT / "data" / "enriched" / "all-vendors.csv"
SUBSET_CSV = ROOT / "tmp" / "orange-enrich-subset.csv"
UPDATES_CSV = ROOT / "tmp" / "orange-enrich-subset.out.csv"
MERGE_REPORT = ROOT / "tmp" / "orange-merge-report.txt"


def normalize_key_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def row_key(row: dict[str, str]) -> tuple[str, str]:
    county = normalize_key_text(row.get("county", ""))
    vendor = normalize_key_text(row.get("vendor_name", ""))
    return county, vendor


def is_orange(row: dict[str, str]) -> bool:
    return (row.get("county") or "").strip().lower() == "orange"


def is_usable_http_url(url: str) -> bool:
    u = (url or "").strip()
    if not u:
        return False
    p = urlparse(u)
    if p.scheme not in ("http", "https"):
        return False
    host = p.netloc.split("@")[-1].split(":")[0]
    if not host or any(c in host for c in " \t\n\r"):
        return False
    return True


def suspicious_url_reason(url: str) -> str | None:
    u = (url or "").strip()
    if not u:
        return "no website"
    lower = u.lower()
    if any(x in lower for x in ("example.com", "yourdomain", "placeholder", "localhost")):
        return "placeholder/invalid host"
    if not is_usable_http_url(u):
        return "invalid host or scheme"
    return None


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})


def build_subset() -> tuple[int, list[str]]:
    source_fields, source_rows = read_csv(SOURCE_CSV)
    master_fields, _ = read_csv(MASTER_CSV)
    out_fields = master_fields if master_fields else source_fields
    orange_rows = [r for r in source_rows if is_orange(r)]
    safe_rows = []
    for r in orange_rows:
        merged = {k: "" for k in out_fields}
        for k in out_fields:
            merged[k] = r.get(k, "")
        safe_rows.append(merged)
    write_csv(SUBSET_CSV, out_fields, safe_rows)
    return len(safe_rows), out_fields


def merge_updates() -> dict[str, object]:
    master_fields, master_rows = read_csv(MASTER_CSV)
    _, update_rows = read_csv(UPDATES_CSV)

    update_map: dict[tuple[str, str], dict[str, str]] = {}
    update_dupes = 0
    for r in update_rows:
        k = row_key(r)
        if k in update_map:
            update_dupes += 1
        update_map[k] = r

    orange_master_keys: Counter[tuple[str, str]] = Counter()
    for r in master_rows:
        if is_orange(r):
            orange_master_keys[row_key(r)] += 1
    master_dup_conflicts = sum(1 for _, c in orange_master_keys.items() if c > 1)

    used_keys: set[tuple[str, str]] = set()
    replaced = 0
    merged_rows: list[dict[str, str]] = []
    image_fields = ("logo_path", "instructor_image_paths", "training_image_paths")

    def normalize_image_field_value(v: str) -> str:
        if not v:
            return v
        parts = []
        for part in v.split("|"):
            p = part.strip()
            if not p:
                continue
            if p.startswith("images/"):
                parts.append(p)
            elif p.startswith("orange/"):
                parts.append(f"images/{p}")
            else:
                parts.append(p)
        return "|".join(parts)

    for r in master_rows:
        if is_orange(r):
            k = row_key(r)
            if k in update_map:
                new_row = {col: update_map[k].get(col, "") for col in master_fields}
                for f in image_fields:
                    new_row[f] = normalize_image_field_value(new_row.get(f, ""))
                merged_rows.append(new_row)
                used_keys.add(k)
                replaced += 1
                continue
        merged_rows.append({col: r.get(col, "") for col in master_fields})

    write_csv(MASTER_CSV, master_fields, merged_rows)
    unmatched = sorted(set(update_map.keys()) - used_keys)

    return {
        "replaced": replaced,
        "unmatched_keys": unmatched,
        "update_duplicate_conflicts": update_dupes,
        "master_duplicate_conflicts": master_dup_conflicts,
    }


def copy_orange_images() -> tuple[int, list[str]]:
    src_base = ROOT / "tmp" / "images" / "orange"
    dest_base = ROOT / "data" / "enriched" / "images" / "orange"
    copied = 0
    copied_slugs: list[str] = []
    if not src_base.exists():
        return copied, copied_slugs
    dest_base.mkdir(parents=True, exist_ok=True)
    for slug_dir in sorted(p for p in src_base.iterdir() if p.is_dir()):
        dest = dest_base / slug_dir.name
        shutil.copytree(slug_dir, dest, dirs_exist_ok=True)
        copied += 1
        copied_slugs.append(slug_dir.name)
    return copied, copied_slugs


def gather_post_retry_stats() -> dict[str, object]:
    _, master_rows = read_csv(MASTER_CSV)
    orange_rows = [r for r in master_rows if is_orange(r)]
    crawl_counts = Counter((r.get("crawl_status") or "").strip() for r in orange_rows)
    failed_vendors = sorted(
        (r.get("vendor_name") or "").strip()
        for r in orange_rows
        if (r.get("crawl_status") or "").strip() in {"failed", "parse_error"}
    )
    suspicious = []
    for r in orange_rows:
        reason = suspicious_url_reason(r.get("website_url", ""))
        if reason:
            suspicious.append(
                f"{(r.get('vendor_name') or '').strip()} -> {(r.get('website_url') or '').strip() or '<empty>'} ({reason})"
            )
    return {
        "orange_rows": len(orange_rows),
        "crawl_counts": crawl_counts,
        "failed_vendors": failed_vendors,
        "suspicious_urls": sorted(suspicious),
    }


def main() -> None:
    orange_target_count, subset_fields = build_subset()
    print(f"Built subset: {SUBSET_CSV} ({orange_target_count} rows, {len(subset_fields)} columns)")
    if not UPDATES_CSV.exists():
        raise SystemExit(f"Missing updates CSV: {UPDATES_CSV}")

    merge_stats = merge_updates()
    copied_count, copied_slugs = copy_orange_images()
    post = gather_post_retry_stats()

    lines = []
    lines.append("Orange enrichment rerun report")
    lines.append("=" * 32)
    lines.append(f"Orange target row count: {orange_target_count}")
    lines.append("")
    lines.append("Crawl status counts (orange rows in master after merge):")
    for key in ("success", "failed", "no_website", "parse_error"):
        lines.append(f"  {key}: {post['crawl_counts'].get(key, 0)}")
    lines.append("")
    lines.append("Merge stats:")
    lines.append(f"  rows replaced: {merge_stats['replaced']}")
    lines.append(f"  unmatched keys: {len(merge_stats['unmatched_keys'])}")
    lines.append(f"  duplicate key conflicts (updates): {merge_stats['update_duplicate_conflicts']}")
    lines.append(f"  duplicate key conflicts (master orange): {merge_stats['master_duplicate_conflicts']}")
    if merge_stats["unmatched_keys"]:
        lines.append("  unmatched key list:")
        for county, vendor in merge_stats["unmatched_keys"]:
            lines.append(f"    - {county} :: {vendor}")
    lines.append("")
    lines.append(f"Orange image slug folders copied from tmp/images/orange -> data/enriched/images/orange: {copied_count}")
    if copied_slugs:
        lines.append("  copied slugs:")
        for s in copied_slugs:
            lines.append(f"    - {s}")
    lines.append("")
    lines.append("Orange vendors still failed after retry:")
    if post["failed_vendors"]:
        for v in post["failed_vendors"]:
            lines.append(f"  - {v}")
    else:
        lines.append("  - none")
    lines.append("")
    lines.append("Suspicious URLs (invalid host/placeholder/no website):")
    if post["suspicious_urls"]:
        for s in post["suspicious_urls"]:
            lines.append(f"  - {s}")
    else:
        lines.append("  - none")

    text = "\n".join(lines) + "\n"
    MERGE_REPORT.write_text(text, encoding="utf-8")
    print(text)
    print(f"Report written: {MERGE_REPORT}")


if __name__ == "__main__":
    main()
