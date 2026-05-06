# CCW Enrichment (Internal Ops Tool)

Standalone internal data-enrichment app for CCW vendor directory operations.

## Stack
- Next.js + TypeScript
- Supabase Postgres
- Playwright + Cheerio crawling
- OpenAI for selective extraction fallback

## Setup
1. Copy `.env.example` to `.env.local` and fill values.
2. Install dependencies: `npm install`
3. Run DB migrations in Supabase SQL editor (in order):
   - `supabase/migrations/0001_init.sql` — core schema
   - `supabase/migrations/0002_enrichment_jobs.sql` — job queue + RPCs
   - `supabase/migrations/0003_seed_california_counties.sql` — all 58 CA counties (idempotent)
   - `supabase/migrations/0004_enriched_vendor_county_listings.sql` — directory listings table (created as `enriched_vendor_county_listings`, renamed in 0006)
   - `supabase/migrations/0005_add_google_place_columns.sql` — `google_place_id` / `google_reviews_url` on listings
   - `supabase/migrations/0006_rename_enriched_vendor_to_carry_class_vendor_data.sql` — rename listings table to `carry_class_vendor_data` (CSV sync target)
4. Start app: `npm run dev`

## MVP Routes
- `/import`
- `/queue/enrichment` — county filter, pagination, "Enqueue County" button
- `/queue/review`
- `/vendors`
- `/exports`

## Hybrid Architecture

The app uses a **hybrid** model: the Next.js app handles the UI and fast
enqueue requests; a separate **Node worker** processes enrichment jobs at a
controlled rate.

### How it works

1. **Enqueue** — Hit `POST /api/enrichment/enqueue` with `{ "county": "san-diego" }` (or use the "Enqueue" button on the queue page). This creates an `enrichment_runs` row scoped to the county and inserts one `enrichment_jobs` row per eligible vendor.
2. **Worker polls** — `npm run worker` starts a long-running process that calls the Postgres `claim_enrichment_jobs` RPC (uses `FOR UPDATE SKIP LOCKED`), runs `enrichVendor()` with concurrency/rate limits, and marks each job completed or failed.
3. **Retries** — Transient failures are retried up to `max_attempts` (default 3). The worker re-queues the job on failure; after exhausting attempts it marks `failed` with an error summary.

### Running the worker

```bash
# Uses .env.local for config
npm run worker
```

Ctrl-C triggers graceful shutdown (in-flight jobs finish before exit).

### Rate limit configuration

All tuneable via environment variables (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `ENRICHMENT_GLOBAL_CONCURRENCY` | `3` | Max vendor enrichments running at once |
| `ENRICHMENT_PER_HOST_CONCURRENCY` | `1` | Max concurrent HTTP requests to one hostname |
| `ENRICHMENT_REQUEST_DELAY_MS` | `1500` | Pause between requests to the same host (ms) |
| `ENRICHMENT_POLL_INTERVAL_S` | `5` | Seconds between queue polls when idle |
| `ENRICHMENT_MAX_RETRIES` | `2` | Max retries (p-retry) for transient crawl failures |

For a full county like San Diego (~100+ vendors), the defaults give a
conservative crawl rate: ~3 vendors in parallel, at most 1 request per host
at a time, with 1.5 s + jitter between requests to the same domain.

## Google Place ID backfill (directory listings)

Use `scripts/backfill-google-place-ids.ts` to resolve Google Place IDs from vendor name + location via official Places APIs (Find Place → Text Search fallback → selective Place Details). Results merge into CSV columns `google_place_id`, `google_reviews_url`, plus QA columns `match_confidence`, `match_reason`, `raw_candidate_place_ids`, `error_message`.

### Env setup

- Add `GOOGLE_PLACES_API_KEY` to `.env.local` (see `.env.example`).
- Apply migration `supabase/migrations/0005_add_google_place_columns.sql` before reloading enriched CSV into Supabase.

### Commands (repo root)

Dry-run (no files written; still calls Google APIs):

```bash
npm run google-placeids:backfill -- --dry-run
```

Apply → write `ccw-scraper/data/enriched/all-vendors.with-google-placeids.csv` + review/checkpoint/cache under `tmp/`:

```bash
npm run google-placeids:backfill -- --apply
```

Apply in-place on canonical CSV (timestamped backup next to `all-vendors.csv`):

```bash
npm run google-placeids:backfill -- --apply --in-place
```

Optional: include medium-confidence matches when filling IDs:

```bash
npm run google-placeids:backfill -- --apply --apply-confidence=high,medium
```

Reload Supabase from CSV (full replace — requires migration `0005` applied):

```bash
npm run db:load-enriched
```

Optional direct Supabase updates (still merges QA columns to output CSV when `--apply`):

```bash
npm run google-placeids:backfill -- --apply --source=supabase --apply-supabase
```

### Review output

Open `tmp/google-placeid-review-needed.csv` for rows where `match_confidence` is not `high`. After manual fixes, merge IDs into `all-vendors.csv` or rerun with stricter inputs.

## Notes
- This is intentionally a production-minded MVP scaffold.
- Deterministic extraction runs first; AI is reserved for ambiguous cases.
- Evidence and confidence are stored for auditability and review.
- The worker runs anywhere Node runs (local machine, small VM, Railway, Fly, etc.). It does **not** need Vercel.
