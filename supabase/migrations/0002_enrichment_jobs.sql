-- Lightweight job table that the worker polls.
-- Each row = one vendor enrichment to perform within a run.
create table if not exists enrichment_jobs (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references enrichment_runs(id) on delete cascade,
  vendor_id uuid not null references vendors(id) on delete cascade,
  status run_status not null default 'queued',
  claimed_at timestamptz,
  started_at timestamptz,
  completed_at timestamptz,
  attempts integer not null default 0,
  max_attempts integer not null default 3,
  error_summary text,
  created_at timestamptz not null default now()
);

create index enrichment_jobs_poll_idx
  on enrichment_jobs(status, created_at)
  where status = 'queued';

create unique index enrichment_jobs_run_vendor_idx
  on enrichment_jobs(run_id, vendor_id);

-- RPC: atomically claim the next N queued jobs (skip locked).
create or replace function claim_enrichment_jobs(batch_size int default 1)
returns setof enrichment_jobs
language sql volatile
as $$
  update enrichment_jobs
  set status = 'running',
      claimed_at = now(),
      attempts = attempts + 1
  where id in (
    select id from enrichment_jobs
    where status = 'queued'
    order by created_at
    for update skip locked
    limit batch_size
  )
  returning *;
$$;

-- RPC: enqueue all vendors for a county that have not already been
-- queued/completed in the given run.
create or replace function enqueue_county_vendors(
  p_run_id uuid,
  p_county_id uuid,
  p_max_attempts int default 3
)
returns int
language plpgsql volatile
as $$
declare
  inserted int;
begin
  insert into enrichment_jobs (run_id, vendor_id, max_attempts)
  select p_run_id, v.id, p_max_attempts
  from vendors v
  join vendor_county_listings vcl on vcl.vendor_id = v.id
  where vcl.county_id = p_county_id
    and v.status in ('new', 'ready_for_enrichment', 'needs_review')
    and not exists (
      select 1 from enrichment_jobs ej
      where ej.run_id = p_run_id and ej.vendor_id = v.id
    )
  on conflict (run_id, vendor_id) do nothing;

  get diagnostics inserted = row_count;
  return inserted;
end;
$$;
