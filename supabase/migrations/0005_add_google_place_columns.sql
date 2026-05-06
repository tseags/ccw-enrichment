alter table enriched_vendor_county_listings
  add column if not exists google_place_id text,
  add column if not exists google_reviews_url text;

create index if not exists enriched_vendor_county_listings_google_place_id_idx
  on enriched_vendor_county_listings (google_place_id);
