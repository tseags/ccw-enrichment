#!/usr/bin/env python3
"""Website URL backfill: snapshots, per-county ingest with retries, validation, combine."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
VENV_PY = REPO / ".venv" / "bin" / "python"
RUN_INGEST = REPO / "run_ingest.py"
JSONL_TO_CSV = REPO / "scripts" / "jsonl_to_csv.py"
SNAP_DIR = REPO / "tmp" / "backfill-before"
REPORT_PATH = REPO / "tmp" / "backfill-report.json"

EXPECTED_HEADER = [
    "county",
    "vendor_name",
    "instructor_names",
    "website_url",
    "phone",
    "email",
    "city",
    "state",
    "source_url",
    "source_type",
]

BACKOFF_S = [2, 4, 8, 16, 32]
MAX_ATTEMPTS = 5
HAIKU_MODEL = "claude-haiku-4-5-20251001"


def is_canonical_jsonl(p: Path) -> bool:
    if p.suffix != ".jsonl":
        return False
    name = p.name
    if ".before-" in name:
        return False
    return True


def empty_url(v: object) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def jsonl_out_for_slug(slug: str) -> Path:
    if slug == "san-diego":
        return DATA / "san_diego.jsonl"
    return DATA / f"{slug}.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def county_metrics(rows: list[dict]) -> dict:
    total = len(rows)
    empty = sum(1 for r in rows if empty_url(r.get("website_url")))
    return {"total": total, "with_url": total - empty, "empty_url": empty}


def norm_vendor(name: str) -> str:
    return (name or "").strip().lower()


def stable_key(county: str, vendor_name: str) -> str:
    return f"{(county or '').strip().lower()}|{norm_vendor(vendor_name)}"


def canonical_jsonl_paths() -> list[Path]:
    return sorted(p for p in DATA.glob("*.jsonl") if is_canonical_jsonl(p))


def discover_targets() -> tuple[list[str], dict]:
    jsonl_files = canonical_jsonl_paths()
    counties_empty: set[str] = set()
    for jp in jsonl_files:
        for o in load_jsonl(jp):
            c = (o.get("county") or "").strip().lower()
            if empty_url(o.get("website_url")):
                counties_empty.add(c)
    csv_empty: set[str] = set()
    with (DATA / "all-vendors.csv").open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if list(r.fieldnames) != EXPECTED_HEADER:
            raise SystemExit(f"CSV header mismatch: {r.fieldnames}")
        for row in r:
            c = (row.get("county") or "").strip().lower()
            if c and empty_url(row.get("website_url")):
                csv_empty.add(c)
    target = sorted(counties_empty | csv_empty)
    pre = {
        "jsonl_counties_with_empty": sorted(counties_empty),
        "csv_counties_with_empty": sorted(csv_empty),
        "target_union": target,
    }
    return target, pre


def run_ingest_subprocess(slug: str, out_path: Path, extra_env: dict | None) -> tuple[int, str, str]:
    env = None
    if extra_env:
        import os

        env = os.environ.copy()
        env.update(extra_env)
    cmd = [
        str(VENV_PY),
        str(RUN_INGEST),
        "--county",
        slug,
        "--output",
        str(out_path),
    ]
    p = subprocess.run(
        cmd,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env=env,
    )
    return p.returncode, p.stdout, p.stderr


def ingest_with_retries(slug: str, out_path: Path) -> tuple[bool, str]:
    """Up to 5 attempts default model, then up to 5 with haiku. Returns (ok, detail)."""
    chunks: list[str] = []
    for label, model_env in (
        ("default", None),
        ("haiku", {"CLAUDE_MODEL": HAIKU_MODEL}),
    ):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            code, out, err = run_ingest_subprocess(slug, out_path, model_env)
            msg = f"[{label}] attempt {attempt}/{MAX_ATTEMPTS} rc={code}\nstdout:\n{out}\nstderr:\n{err}"
            chunks.append(msg)
            if code == 0:
                return True, "\n\n".join(chunks)
            if attempt < MAX_ATTEMPTS:
                time.sleep(BACKOFF_S[attempt - 1])
    return False, "\n\n".join(chunks)


def validate_vs_before(before_rows: int, after_rows: int, slug: str) -> tuple[bool, str]:
    if after_rows == 0 and before_rows > 0:
        return False, f"{slug}: after row count is zero (before={before_rows})"
    if before_rows > 0 and after_rows < before_rows:
        return False, f"{slug}: row count decreased before={before_rows} after={after_rows}"
    return True, ""


def main() -> int:
    if not VENV_PY.is_file():
        print("Missing .venv; create venv first", file=sys.stderr)
        return 1

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DATA / "all-vendors.csv", SNAP_DIR / "all-vendors.before.csv")

    targets, preflight = discover_targets()

    pre_metrics: dict[str, dict] = {}
    for slug in targets:
        jp = jsonl_out_for_slug(slug)
        if not jp.is_file():
            print(f"Missing expected file {jp} for {slug}", file=sys.stderr)
            return 1
        dest = SNAP_DIR / jp.name
        shutil.copy2(jp, dest)
        pre_metrics[slug] = county_metrics(load_jsonl(jp))

    overall_pre = {"total": 0, "with_url": 0, "empty_url": 0}
    for m in pre_metrics.values():
        for k in overall_pre:
            overall_pre[k] += m[k]

    metrics_path = SNAP_DIR / "metrics.json"
    metrics_path.write_text(
        json.dumps(
            {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "preflight": preflight,
                "per_county_before": pre_metrics,
                "overall_before": overall_pre,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    results: list[dict] = []
    commands_run: list[str] = []

    for slug in targets:
        out_path = jsonl_out_for_slug(slug)
        before_rows = pre_metrics[slug]["total"]
        ok, detail = ingest_with_retries(slug, out_path)
        commands_run.append(
            f".venv/bin/python run_ingest.py --county {slug} --output {out_path.relative_to(REPO)} "
            f"(with up to {MAX_ATTEMPTS} backoff retries, then haiku x{MAX_ATTEMPTS})"
        )
        after = load_jsonl(out_path) if out_path.is_file() else []
        after_rows = len(after)
        vok, vmsg = validate_vs_before(before_rows, after_rows, slug)
        entry = {
            "county_slug": slug,
            "ingest_ok": ok,
            "validation_ok": vok,
            "before_total": before_rows,
            "after_total": after_rows,
            "detail": detail if not ok else "",
            "validation_message": vmsg,
        }
        if ok and not vok:
            # restore from snapshot
            snap = SNAP_DIR / out_path.name
            shutil.copy2(snap, out_path)
            entry["restored_from_snapshot"] = True
            entry["after_total"] = before_rows
        elif not ok:
            snap = SNAP_DIR / out_path.name
            shutil.copy2(snap, out_path)
            entry["restored_from_snapshot"] = True

        results.append(entry)

    # Post metrics from disk
    per_after: dict[str, dict] = {}
    for slug in targets:
        jp = jsonl_out_for_slug(slug)
        per_after[slug] = county_metrics(load_jsonl(jp))

    # Counties not re-run: load from disk for full picture
    all_canon = canonical_jsonl_paths()
    full_after: dict[str, list[dict]] = defaultdict(list)
    for jp in all_canon:
        for o in load_jsonl(jp):
            c = (o.get("county") or "").strip().lower()
            full_after[c].append(o)

    overall_after = {"total": 0, "with_url": 0, "empty_url": 0}
    for rows in full_after.values():
        m = county_metrics(rows)
        for k in overall_after:
            overall_after[k] += m[k]

    # Recovered list (only re-run counties): empty before -> non-empty after
    recovered: list[dict] = []
    for slug in targets:
        snap_path = SNAP_DIR / jsonl_out_for_slug(slug).name
        before_map: dict[str, str] = {}
        for ob in load_jsonl(snap_path):
            k = stable_key(str(ob.get("county", "")), str(ob.get("vendor_name", "")))
            wb = "" if empty_url(ob.get("website_url")) else str(ob.get("website_url")).strip()
            before_map[k] = wb
        for o in load_jsonl(jsonl_out_for_slug(slug)):
            k = stable_key(str(o.get("county", "")), str(o.get("vendor_name", "")))
            wb = before_map.get(k, "")
            wa = "" if empty_url(o.get("website_url")) else str(o.get("website_url")).strip()
            if wb == "" and wa != "":
                raw = o.get("raw_block")
                recovered.append(
                    {
                        "county": o.get("county"),
                        "vendor_name": o.get("vendor_name"),
                        "website_before": wb,
                        "website_after": wa,
                        "source_type": o.get("source_type"),
                        "_raw_block": raw if isinstance(raw, str) else None,
                    }
                )

    # Combine — explicit canonical paths only
    combine_inputs = [str(p.relative_to(REPO)) for p in canonical_jsonl_paths()]
    combine_cmd = [
        str(VENV_PY),
        str(JSONL_TO_CSV),
        "--combine",
        "-o",
        "data/all-vendors.csv",
        *combine_inputs,
    ]
    commands_run.append(" ".join(combine_cmd))
    p = subprocess.run(combine_cmd, cwd=str(REPO), capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stderr, file=sys.stderr)
        return p.returncode

    csv_before_path = SNAP_DIR / "all-vendors.before.csv"

    def csv_keys(path: Path) -> list[str]:
        keys: list[str] = []
        with path.open(newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                keys.append(
                    stable_key(row.get("county", ""), row.get("vendor_name", ""))
                )
        return keys

    keys_old = csv_keys(csv_before_path)
    keys_new = csv_keys(DATA / "all-vendors.csv")
    ordering_note = "unchanged" if keys_old == keys_new else (
        f"row order changed: len before={len(keys_old)} after={len(keys_new)}; "
        f"first differing index next"
    )
    diff_idx = None
    if keys_old != keys_new:
        for i, (a, b) in enumerate(zip(keys_old, keys_new)):
            if a != b:
                diff_idx = i
                break
        if diff_idx is None and len(keys_old) != len(keys_new):
            diff_idx = min(len(keys_old), len(keys_new))

    succeeded = [r["county_slug"] for r in results if r["ingest_ok"] and r["validation_ok"]]
    failed = [r["county_slug"] for r in results if not (r["ingest_ok"] and r["validation_ok"])]

    def pdf_hyperlink_check(row: dict) -> dict:
        st = row.get("source_type")
        url = (row.get("website_after") or "").strip()
        rb = row.get("_raw_block") or ""
        if not isinstance(rb, str):
            rb = ""
        has_marker = "Hyperlinks on this page" in rb
        url_in_block = bool(url) and url in rb
        return {
            "county": row.get("county"),
            "vendor_name": row.get("vendor_name"),
            "source_type": st,
            "has_hyperlink_section": has_marker,
            "url_appears_in_raw_block": url_in_block,
            "raw_block_excerpt": (rb[:1200] + "…") if len(rb) > 1200 else rb,
        }

    pdf_recovered = [
        r for r in recovered if r.get("source_type") in ("pdf", "google_drive_pdf")
    ]
    by_county_pdf: dict[str, list[dict]] = defaultdict(list)
    for row in pdf_recovered:
        by_county_pdf[str(row.get("county") or "")].append(row)
    hyperlink_evidence_samples: list[dict] = []
    counties_rr = sorted(by_county_pdf.keys())
    while len(hyperlink_evidence_samples) < min(12, len(pdf_recovered)) and counties_rr:
        progressed = False
        for c in list(counties_rr):
            if len(hyperlink_evidence_samples) >= 12:
                break
            bucket = by_county_pdf.get(c) or []
            if not bucket:
                counties_rr.remove(c)
                continue
            hyperlink_evidence_samples.append(pdf_hyperlink_check(bucket.pop(0)))
            progressed = True
        if not progressed:
            break

    recovered_clean = []
    for row in recovered:
        row = dict(row)
        row.pop("_raw_block", None)
        recovered_clean.append(row)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commands_run": commands_run,
        "target_counties": targets,
        "succeeded": succeeded,
        "failed": failed,
        "per_county_results": results,
        "per_county_after_metrics": per_after,
        "overall_before": overall_pre,
        "overall_after": overall_after,
        "total_recovered_websites": len(recovered_clean),
        "recovered_rows": recovered_clean,
        "hyperlink_evidence_samples": hyperlink_evidence_samples,
        "csv_ordering": {
            "note": ordering_note,
            "first_diff_index": diff_idx,
        },
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({"succeeded": len(succeeded), "failed": len(failed), "recovered": len(recovered)}, indent=2))
    return 0 if not failed else 0  # still exit 0 if we continued; failures in report


if __name__ == "__main__":
    raise SystemExit(main())
