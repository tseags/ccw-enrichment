-- Flat enriched listings from ccw-scraper/data/enriched/all-vendors.csv (one row per vendor+county).
-- Loaded via: npm run db:load-enriched

create table enriched_vendor_county_listings (
  id uuid primary key default gen_random_uuid(),
  county text not null,
  needs_review text,
  vendor_name text not null,
  instructor_names text,
  email text,
  phone text,
  website_url text,
  booking_capability text,
  city text,
  state text,
  address text,
  price_16hr_full text,
  price_8hr_renewal text,
  price_add_a_gun text,
  vendor_description text,
  crawl_status text,
  enrichment_confidence text,
  confidence_notes text,
  logo_path text,
  instructor_image_paths text,
  training_image_paths text,
  enriched_at timestamptz,
  normalized_vendor_name text generated always as (lower(trim(vendor_name))) stored,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint enriched_vendor_county_listings_uniq unique (county, normalized_vendor_name)
);

create index enriched_vendor_county_listings_vendor_idx
  on enriched_vendor_county_listings (normalized_vendor_name);

create or replace function enriched_vendor_county_listings_set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger enriched_vendor_county_listings_updated_at
  before update on enriched_vendor_county_listings
  for each row
  execute procedure enriched_vendor_county_listings_set_updated_at();

alter table enriched_vendor_county_listings enable row level security;

create policy enriched_vendor_county_listings_select_public
  on enriched_vendor_county_listings
  for select
  to anon, authenticated
  using (true);

comment on table enriched_vendor_county_listings is 'Public directory data synced from ccw-scraper enriched CSV; RLS allows read-only public select.';
