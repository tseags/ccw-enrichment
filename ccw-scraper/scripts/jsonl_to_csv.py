#!/usr/bin/env python3
"""Convert vendor JSONL rows to CSV (same layout as data/san_diego.csv).

Usage:
  From repo ``ccw-scraper/``:

  - Convert every ``data/*.jsonl`` next to a matching ``*.csv``::

      python scripts/jsonl_to_csv.py

  - Convert specific files (output path defaults to the same basename with ``.csv``)::

      python scripts/jsonl_to_csv.py data/san_diego.jsonl data/orange.jsonl

  - Write CSV to an explicit path (one input file only)::

      python scripts/jsonl_to_csv.py data/san_diego.jsonl -o /tmp/out.csv

  - Merge every ``data/*.jsonl`` into one CSV (same columns, UTF-8)::

      python scripts/jsonl_to_csv.py --combine

  - Merge specific JSONL files into one output::

      python scripts/jsonl_to_csv.py --combine -o data/vendors.csv data/a.jsonl data/b.jsonl

Columns (order): county, vendor_name, instructor_names, website_url, phone, email,
city, state, source_url, source_type. ``instructor_names`` is joined with ``"; "``.
``raw_block`` and any other extra JSON keys are not written. UTF-8; uses the stdlib
``csv`` module for quoting.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

FIELDNAMES = [
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


def _text_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _instructor_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [str(x) for x in value if x is not None and str(x).strip() != ""]
        return "; ".join(parts)
    return str(value)


def _row_from_record(obj: dict[str, object]) -> dict[str, str]:
    return {
        "county": _text_cell(obj.get("county")),
        "vendor_name": _text_cell(obj.get("vendor_name")),
        "instructor_names": _instructor_cell(obj.get("instructor_names")),
        "website_url": _text_cell(obj.get("website_url")),
        "phone": _text_cell(obj.get("phone")),
        "email": _text_cell(obj.get("email")),
        "city": _text_cell(obj.get("city")),
        "state": _text_cell(obj.get("state")),
        "source_url": _text_cell(obj.get("source_url")),
        "source_type": _text_cell(obj.get("source_type")),
    }


def combine_jsonl_files_to_csv(jsonl_paths: list[Path], csv_path: Path) -> int:
    """Write one CSV with rows from all JSONL files in path order. Returns row count."""
    csv_path = csv_path.resolve()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with csv_path.open("w", encoding="utf-8", newline="") as cf:
        writer = csv.DictWriter(cf, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for jsonl_path in jsonl_paths:
            jsonl_path = jsonl_path.resolve()
            with jsonl_path.open(encoding="utf-8") as jf:
                for line_no, line in enumerate(jf, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError as e:
                        raise ValueError(f"{jsonl_path}:{line_no}: invalid JSON: {e}") from e
                    if not isinstance(obj, dict):
                        raise ValueError(f"{jsonl_path}:{line_no}: expected JSON object")
                    writer.writerow(_row_from_record(obj))
                    n += 1
    return n


def convert_jsonl_to_csv(jsonl_path: Path, csv_path: Path) -> None:
    jsonl_path = jsonl_path.resolve()
    csv_path = csv_path.resolve()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open(encoding="utf-8") as jf, csv_path.open(
        "w", encoding="utf-8", newline=""
    ) as cf:
        writer = csv.DictWriter(cf, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for line_no, line in enumerate(jf, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{jsonl_path}:{line_no}: invalid JSON: {e}") from e
            if not isinstance(obj, dict):
                raise ValueError(f"{jsonl_path}:{line_no}: expected JSON object")
            writer.writerow(_row_from_record(obj))


def _default_jsonl_paths(data_dir: Path) -> list[Path]:
    return sorted(data_dir.glob("*.jsonl"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert vendor JSONL files to CSV.")
    parser.add_argument(
        "--combine",
        action="store_true",
        help="Merge all given JSONL files (or all data/*.jsonl) into a single CSV",
    )
    parser.add_argument(
        "jsonl",
        nargs="*",
        type=Path,
        help="JSONL files (default: all data/*.jsonl under --data-dir)",
    )
    parser.add_argument(
        "-d",
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Directory for default glob when no inputs are given (default: data)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help=(
            "Output CSV path: with --combine defaults to data/all-vendors.csv; "
            "without --combine, only when exactly one input JSONL is given"
        ),
    )
    args = parser.parse_args(argv)

    inputs = list(args.jsonl)
    if not inputs:
        inputs = _default_jsonl_paths(args.data_dir)
        if not inputs:
            print(f"No *.jsonl files found in {args.data_dir.resolve()}", file=sys.stderr)
            return 1

    if args.combine:
        out = args.output if args.output is not None else args.data_dir / "all-vendors.csv"
        n = combine_jsonl_files_to_csv(inputs, out)
        print(f"Wrote {n} data rows (+ header) to {out.resolve()}")
        return 0

    if args.output is not None and len(inputs) != 1:
        print("-o/--output without --combine requires exactly one input JSONL file", file=sys.stderr)
        return 2

    for jp in inputs:
        out = args.output if args.output is not None else jp.with_suffix(".csv")
        convert_jsonl_to_csv(jp, out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
