#!/usr/bin/env python3
"""CLI entrypoint for county CCW vendor ingests."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from ingest.county_registry import COUNTIES  # noqa: E402

# Counties with a hand-tuned ingest module (class follows TitleCaseIngest naming).
CUSTOM_MODULES: dict[str, str] = {
    "san-diego": "ingest.san_diego",
}

# All source_type="pdf" or "google_drive_pdf" slugs that use the generic PDF pipeline.
_PDF_SLUGS: set[str] = {
    slug for slug, meta in COUNTIES.items()
    if meta["source_type"] in ("pdf", "google_drive_pdf") and slug not in CUSTOM_MODULES
}

# All source_type="webpage" slugs that use the generic webpage pipeline.
_WEBPAGE_SLUGS: set[str] = {
    slug for slug, meta in COUNTIES.items()
    if meta["source_type"] == "webpage"
}

# Union of everything we can run today.
SUPPORTED_SLUGS: set[str] = set(CUSTOM_MODULES) | _PDF_SLUGS | _WEBPAGE_SLUGS


def main() -> None:
    p = argparse.ArgumentParser(description="Ingest CCW vendor lists by county.")
    p.add_argument("--county", required=True, help="County slug, e.g. san-diego")
    p.add_argument("--output", required=True, help="Output JSONL path")
    p.add_argument(
        "--list", action="store_true", dest="list_counties",
        help="Print all supported county slugs and exit",
    )
    args = p.parse_args()

    if args.list_counties:
        for s in sorted(SUPPORTED_SLUGS):
            if s in CUSTOM_MODULES:
                tag = "custom"
            elif s in _WEBPAGE_SLUGS:
                tag = "generic-webpage"
            else:
                tag = "generic-pdf"
            print(f"  {s:24s} [{tag}]")
        sys.exit(0)

    slug = args.county.strip().lower()

    if slug in CUSTOM_MODULES:
        mod = importlib.import_module(CUSTOM_MODULES[slug])
        class_name = "".join(part.title() for part in slug.split("-")) + "Ingest"
        IngestClass = getattr(mod, class_name)
        ingest = IngestClass()
    elif slug in _PDF_SLUGS:
        from ingest.generic_pdf import GenericPdfIngest
        ingest = GenericPdfIngest(slug)
    elif slug in _WEBPAGE_SLUGS:
        from ingest.generic_webpage import GenericWebpageIngest
        ingest = GenericWebpageIngest(slug)
    else:
        sys.stderr.write(
            f"Unsupported county: {args.county!r}.\n"
            f"Supported: {sorted(SUPPORTED_SLUGS)}\n"
        )
        sys.exit(1)

    records = ingest.run()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"Wrote {len(records)} records to {out_path}")


if __name__ == "__main__":
    main()
