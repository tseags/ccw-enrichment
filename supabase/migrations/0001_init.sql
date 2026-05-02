create extension if not exists pgcrypto;

create type source_type as enum ('pdf', 'webpage', 'manual');
create type parse_status as enum ('pending', 'parsed', 'failed');
create type run_trigger_type as enum ('manual', 'batch', 'scheduled');
create type run_scope_type as enum ('vendor', 'county', 'all');
create type run_status as enum ('queued', 'running', 'completed', 'failed');
create type enrichment_stage as enum ('website', 'crawl', 'pricing', 'booking', 'finalize');
create type stage_status as enum ('queued', 'running', 'completed', 'failed', 'skipped');
create type retrieval_method as enum ('http', 'playwright');
create type extractor_type as enum ('deterministic', 'ai');
create type booking_capability as enum ('direct_booking', 'inquiry_only', 'none', 'unclear');
create type review_status as enum ('open', 'in_review', 'resolved', 'dismissed');
create type review_severity as enum ('low', 'medium', 'high', 'critical');
create type export_target_type as enum ('csv', 'google_sheets');
create type export_status as enum ('queued', 'running', 'completed', 'failed');
create type county_listing_status as enum ('active', 'inactive', 'unknown');
create type vendor_status as enum ('new', 'ready_for_enrichment', 'enriched', 'needs_review');

create table counties (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  state text not null default 'CA',
  slug text not null unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table county_sources (
  id uuid primary key default gen_random_uuid(),
  county_id uuid not null references counties(id) on delete cascade,
  source_type source_type not null,
  source_url text,
  storage_path text,
  published_at timestamptz,
  fetched_at timestamptz not null default now(),
  checksum text,
  parse_status parse_status not null default 'pending',
  notes text,
  created_at timestamptz not null default now()
);

create table county_source_records (
  id uuid primary key default gen_random_uuid(),
  county_source_id uuid not null references county_sources(id) on delete cascade,
  row_index integer not null,
  raw_text text not null,
  raw_json jsonb not null default '{}'::jsonb,
  parse_confidence numeric(4,3),
  parse_warnings text[],
  created_at timestamptz not null default now()
);

create unique index county_source_records_unique_row on county_source_records(county_source_id, row_index);

create table vendors (
  id uuid primary key default gen_random_uuid(),
  canonical_name text not null,
  normalized_name text not null,
  website_url text,
  website_confidence numeric(4,3),
  hq_city text,
  status vendor_status not null default 'new',
  last_enriched_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index vendors_normalized_name_idx on vendors(normalized_name);

create table vendor_county_listings (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references vendors(id) on delete cascade,
  county_id uuid not null references counties(id) on delete cascade,
  county_source_id uuid not null references county_sources(id) on delete cascade,
  source_record_id uuid references county_source_records(id) on delete set null,
  listing_status county_listing_status not null default 'active',
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create unique index vendor_county_listing_unique on vendor_county_listings(vendor_id, county_id, county_source_id);

create table vendor_contacts (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references vendors(id) on delete cascade,
  name text,
  role text,
  email text,
  phone text,
  is_primary boolean not null default false,
  source_record_id uuid references county_source_records(id) on delete set null,
  verified_at timestamptz,
  created_at timestamptz not null default now()
);

create table enrichment_runs (
  id uuid primary key default gen_random_uuid(),
  trigger_type run_trigger_type not null,
  scope_type run_scope_type not null,
  scope_ref text,
  status run_status not null default 'queued',
  started_at timestamptz,
  completed_at timestamptz,
  error_summary text,
  created_at timestamptz not null default now()
);

create table vendor_enrichments (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references vendors(id) on delete cascade,
  run_id uuid not null references enrichment_runs(id) on delete cascade,
  stage enrichment_stage not null,
  status stage_status not null default 'queued',
  attempt integer not null default 1,
  started_at timestamptz,
  completed_at timestamptz,
  diagnostics_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create unique index vendor_enrichments_unique_attempt on vendor_enrichments(vendor_id, run_id, stage, attempt);

create table crawl_pages (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references vendors(id) on delete cascade,
  run_id uuid not null references enrichment_runs(id) on delete cascade,
  url text not null,
  final_url text,
  http_status integer,
  content_type text,
  retrieval_method retrieval_method not null,
  page_title text,
  content_hash text,
  raw_text text,
  fetched_at timestamptz not null default now()
);

create table vendor_field_evidence (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references vendors(id) on delete cascade,
  run_id uuid not null references enrichment_runs(id) on delete cascade,
  field_key text not null,
  value_text text,
  value_json jsonb,
  source_url text not null,
  source_type source_type not null default 'webpage',
  evidence_snippet text,
  confidence numeric(4,3) not null,
  extractor_type extractor_type not null,
  extracted_at timestamptz not null default now(),
  is_current boolean not null default true
);

create index vendor_field_evidence_vendor_field_idx on vendor_field_evidence(vendor_id, field_key, is_current);

create table vendor_price_records (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references vendors(id) on delete cascade,
  run_id uuid not null references enrichment_runs(id) on delete cascade,
  course_type text not null,
  price_cents integer,
  currency text not null default 'USD',
  price_text text,
  source_url text not null,
  confidence numeric(4,3) not null,
  evidence_id uuid references vendor_field_evidence(id) on delete set null,
  checked_at timestamptz not null default now()
);

create table vendor_booking_records (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references vendors(id) on delete cascade,
  run_id uuid not null references enrichment_runs(id) on delete cascade,
  booking_capability booking_capability not null,
  booking_url text,
  provider_hint text,
  confidence numeric(4,3) not null,
  evidence_id uuid references vendor_field_evidence(id) on delete set null,
  checked_at timestamptz not null default now()
);

create table review_queue (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references vendors(id) on delete cascade,
  run_id uuid references enrichment_runs(id) on delete set null,
  reason_code text not null,
  severity review_severity not null default 'medium',
  status review_status not null default 'open',
  payload_json jsonb not null default '{}'::jsonb,
  assigned_to text,
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

create unique index review_queue_open_dedupe_idx on review_queue(vendor_id, reason_code) where status in ('open', 'in_review');

create table review_actions (
  id uuid primary key default gen_random_uuid(),
  review_item_id uuid not null references review_queue(id) on delete cascade,
  action_type text not null,
  before_json jsonb,
  after_json jsonb,
  actor text not null default 'system',
  created_at timestamptz not null default now()
);

create table export_jobs (
  id uuid primary key default gen_random_uuid(),
  target_type export_target_type not null,
  status export_status not null default 'queued',
  started_at timestamptz,
  completed_at timestamptz,
  row_count integer,
  error_summary text,
  created_at timestamptz not null default now()
);
