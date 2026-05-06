#!/usr/bin/env bash
set -euo pipefail

# Repo root (parent of scripts/), regardless of cwd or machine path.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CANON="$ROOT/ccw-scraper/data/enriched/all-vendors.csv"
SMOKE_IN="$ROOT/tmp/vendors-placeid-smoke.csv"
SMOKE_OUT="$ROOT/tmp/vendors-placeid-smoke-out.csv"
SMOKE_REVIEW="$ROOT/tmp/google-placeid-review-smoke.csv"
SMOKE_CKPT="$ROOT/tmp/google-placeid-checkpoint-smoke.json"
SMOKE_CACHE="$ROOT/tmp/google-placeid-cache-smoke.json"

cd "$ROOT"
mkdir -p "$ROOT/tmp"

echo "== Smoke CSV: header + 10 rows =="
head -n 11 "$CANON" > "$SMOKE_IN"

echo "== Smoke run (check Summary: no REQUEST_DENIED; some high/medium/low) =="
npm run google-placeids:backfill -- --apply --resume=false \
  --input="$SMOKE_IN" \
  --output="$SMOKE_OUT" \
  --review-output="$SMOKE_REVIEW" \
  --checkpoint="$SMOKE_CKPT" \
  --cache="$SMOKE_CACHE"

echo ""
echo "Smoke outputs:"
echo "  $SMOKE_OUT"
echo "  $SMOKE_REVIEW"
echo ""

if [[ -n "${SKIP_FULL_CONFIRM:-}" ]]; then
  echo "SKIP_FULL_CONFIRM set; skipping pause before full run."
else
  read -r -p "If smoke test looks good, press Enter to run FULL canonical backfill. Ctrl+C to abort. " _
fi

echo "== Full run (default output + review under repo tmp/) =="
npm run google-placeids:backfill -- --apply --resume=false

echo ""
echo "Done. Typical outputs:"
echo "  $ROOT/ccw-scraper/data/enriched/all-vendors.with-google-placeids.csv"
echo "  $ROOT/tmp/google-placeid-review-needed.csv"
