/** Supabase table carry_class_vendor_data — enriched directory rows (one row per vendor × county). */

export const CARRY_CLASS_VENDOR_DATA_COLUMNS = [
  "id",
  "county",
  "needs_review",
  "vendor_name",
  "instructor_names",
  "email",
  "phone",
  "website_url",
  "booking_capability",
  "city",
  "state",
  "address",
  "price_16hr_full",
  "price_8hr_renewal",
  "price_add_a_gun",
  "vendor_description",
  "crawl_status",
  "enrichment_confidence",
  "confidence_notes",
  "normalized_vendor_name",
  "enriched_at",
  "google_place_id",
  "google_reviews_url",
  "logo_path",
  "instructor_image_paths",
  "training_image_paths",
  "created_at",
  "updated_at"
] as const;

export type CarryClassVendorDataColumn = (typeof CARRY_CLASS_VENDOR_DATA_COLUMNS)[number];

export const CARRY_CLASS_VENDOR_DATA_SELECT = CARRY_CLASS_VENDOR_DATA_COLUMNS.join(", ");

/** Row shape for `.select(CARRY_CLASS_VENDOR_DATA_SELECT)` (explicit — dynamic select string is not inferred). */
export type CarryClassVendorDataRow = {
  id: string;
  county: string;
  needs_review: string | null;
  vendor_name: string;
  instructor_names: string | null;
  email: string | null;
  phone: string | null;
  website_url: string | null;
  booking_capability: string | null;
  city: string | null;
  state: string | null;
  address: string | null;
  price_16hr_full: string | null;
  price_8hr_renewal: string | null;
  price_add_a_gun: string | null;
  vendor_description: string | null;
  crawl_status: string | null;
  enrichment_confidence: string | null;
  confidence_notes: string | null;
  normalized_vendor_name: string | null;
  enriched_at: string | null;
  google_place_id: string | null;
  google_reviews_url: string | null;
  logo_path: string | null;
  instructor_image_paths: string | null;
  training_image_paths: string | null;
  created_at: string;
  updated_at: string;
};

export function asCarryClassVendorRows(data: unknown): CarryClassVendorDataRow[] {
  return (data ?? []) as CarryClassVendorDataRow[];
}
