# Deploy: GitHub → Supabase → Vercel

This repo is a **Next.js** app at the root plus **`ccw-scraper/`** (Python enrichment). Production traffic goes to **Vercel**; vendor directory data lives in **Supabase** table `carry_class_vendor_data`, loaded from `ccw-scraper/data/enriched/all-vendors.csv`.

## 1. Supabase project

1. In [Supabase Dashboard](https://supabase.com/dashboard), create a project (pick region, set DB password).
2. Open **Project Settings → API** and copy:
   - **Project URL** → `NEXT_PUBLIC_SUPABASE_URL`
   - **anon public** key → `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - **service_role** key → `SUPABASE_SERVICE_ROLE_KEY` (keep secret; never expose in client-only code)

## 2. Apply database migrations

You need the schema from `supabase/migrations/` on your hosted database.

**Option A — Supabase CLI (recommended)**

```bash
# Install: https://supabase.com/docs/guides/cli
cd /path/to/ccw-enrichment
supabase link --project-ref <your-project-ref>
supabase db push
```

**Option B — SQL editor**

Run each file in order in **SQL Editor** (new query, paste, run):

- `supabase/migrations/0001_init.sql`
- `supabase/migrations/0002_enrichment_jobs.sql`
- `supabase/migrations/0003_seed_california_counties.sql`
- `supabase/migrations/0004_enriched_vendor_county_listings.sql`
- `supabase/migrations/0005_add_google_place_columns.sql`
- `supabase/migrations/0006_rename_enriched_vendor_to_carry_class_vendor_data.sql`

## 3. Load enriched CSV into Supabase

From the **repo root** (same folder as `package.json`), with `.env.local` filled from `.env.example`:

```bash
npm install
npm run db:load-enriched
```

This replaces all rows in `carry_class_vendor_data` with the current `ccw-scraper/data/enriched/all-vendors.csv`.

Whenever you update the CSV locally, commit it, then run `npm run db:load-enriched` again (or run it in CI with secrets—see below).

## 4. GitHub

1. Create a repository (if you have not already) and add this project as `origin`.
2. Commit and push:

```bash
git remote add origin https://github.com/<you>/<repo>.git   # if needed
git add -A
git commit -m "Describe your change"
git push -u origin main
```

3. Optional: in **GitHub → Settings → Secrets and variables → Actions**, add the same three Supabase variables if you use the included workflow (`.github/workflows/ci.yml`).

## 5. Vercel

1. Log in at [vercel.com](https://vercel.com) and **Add New → Project**.
2. **Import** your GitHub repo. Framework: **Next.js** (auto-detected). Root directory: **repository root** (where `package.json` lives).
3. **Environment variables** (Production + Preview), matching `.env.example`:

| Name | Value |
|------|--------|
| `NEXT_PUBLIC_SUPABASE_URL` | Project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | service_role key |

Optional (only if you use those features): `OPENAI_API_KEY`, Google Sheets vars, `IMPORT_FETCH_ALLOWED_HOSTS`, worker tuning vars.

4. Deploy. After the first deploy, open **`/directory`** on your Vercel URL to confirm enriched listings (after step 3 has been run at least once).

## 6. Ongoing updates

1. Update `ccw-scraper/data/enriched/all-vendors.csv` (and run `ccw-scraper` cleanup if you use it).
2. `git push`.
3. Re-run **`npm run db:load-enriched`** against production Supabase (from your machine with `.env.local`, or a small GitHub Action on `workflow_dispatch` with secrets—add if you want automation).

The **pipeline** pages (`/vendors`, queues, etc.) use the older normalized `vendors` table from `0001_init.sql`. The **public-style directory** is **`/directory`**, backed by the enriched CSV table.
