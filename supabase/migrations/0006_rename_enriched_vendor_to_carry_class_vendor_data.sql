-- Rename directory table to carry_class_vendor_data (rows, RLS, and policies move with the table).

alter table public.enriched_vendor_county_listings
  rename to carry_class_vendor_data;

alter index public.enriched_vendor_county_listings_vendor_idx
  rename to carry_class_vendor_data_vendor_idx;

alter index public.enriched_vendor_county_listings_google_place_id_idx
  rename to carry_class_vendor_data_google_place_id_idx;

alter table public.carry_class_vendor_data
  rename constraint enriched_vendor_county_listings_uniq to carry_class_vendor_data_uniq;

alter trigger enriched_vendor_county_listings_updated_at on public.carry_class_vendor_data
  rename to carry_class_vendor_data_updated_at;

comment on table public.carry_class_vendor_data is
  'Carry Class public vendor directory; synced from ccw-scraper enriched CSV; RLS allows read-only public select.';
