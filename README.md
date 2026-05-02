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

## Notes
- This is intentionally a production-minded MVP scaffold.
- Deterministic extraction runs first; AI is reserved for ambiguous cases.
- Evidence and confidence are stored for auditability and review.
- The worker runs anywhere Node runs (local machine, small VM, Railway, Fly, etc.). It does **not** need Vercel.
