import type { NormalizedVendor, RawCountyVendorRow } from "@/lib/types";
import { getSupabaseAdminClient } from "@/lib/db/supabase";

export async function createCountySource(params: {
  countyId: string;
  sourceType: "pdf" | "webpage" | "manual";
  sourceUrl?: string;
  notes?: string;
}) {
  const supabase = getSupabaseAdminClient();
  const { data, error } = await supabase
    .from("county_sources")
    .insert({
      county_id: params.countyId,
      source_type: params.sourceType,
      source_url: params.sourceUrl,
      notes: params.notes
    })
    .select("*")
    .single();
  if (error) throw error;
  return data;
}

export async function insertCountySourceRows(rows: RawCountyVendorRow[]) {
  if (rows.length === 0) return [];
  const supabase = getSupabaseAdminClient();
  const { data, error } = await supabase
    .from("county_source_records")
    .insert(
      rows.map((row) => ({
        county_source_id: row.countySourceId,
        row_index: row.rowIndex,
        raw_text: row.rawText,
        raw_json: row
      }))
    )
    .select("*");
  if (error) throw error;
  return data;
}

export async function upsertVendor(normalized: NormalizedVendor) {
  const supabase = getSupabaseAdminClient();
  const { data: existing } = await supabase
    .from("vendors")
    .select("*")
    .eq("normalized_name", normalized.normalizedName)
    .maybeSingle();
  if (existing) return existing;

  const { data, error } = await supabase
    .from("vendors")
    .insert({
      canonical_name: normalized.canonicalName,
      normalized_name: normalized.normalizedName,
      website_url: normalized.websiteUrl,
      hq_city: normalized.hqCity,
      status: "ready_for_enrichment"
    })
    .select("*")
    .single();
  if (error) throw error;
  return data;
}

export async function createVendorCountyListing(params: {
  vendorId: string;
  countyId: string;
  countySourceId: string;
  sourceRecordId?: string;
}) {
  const supabase = getSupabaseAdminClient();
  const { data, error } = await supabase
    .from("vendor_county_listings")
    .insert({
      vendor_id: params.vendorId,
      county_id: params.countyId,
      county_source_id: params.countySourceId,
      source_record_id: params.sourceRecordId
    })
    .select("*")
    .single();
  if (error) throw error;
  return data;
}

export async function insertVendorContacts(params: {
  vendorId: string;
  contacts: Array<{ name?: string; role?: string; email?: string; phone?: string; isPrimary?: boolean }>;
}) {
  if (params.contacts.length === 0) return [];
  const supabase = getSupabaseAdminClient();
  const { data, error } = await supabase
    .from("vendor_contacts")
    .insert(
      params.contacts.map((contact) => ({
        vendor_id: params.vendorId,
        name: contact.name,
        role: contact.role,
        email: contact.email,
        phone: contact.phone,
        is_primary: Boolean(contact.isPrimary)
      }))
    )
    .select("*");
  if (error) throw error;
  return data;
}

const COUNTY_UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function escapeIlikeLiteral(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/%/g, "\\%").replace(/_/g, "\\_");
}

/** Resolves a county from UUID, slug (e.g. san-diego), or display name. */
export async function resolveCountyId(raw: string): Promise<string> {
  const trimmed = raw.trim();
  if (!trimmed) throw new Error("County is required (UUID, slug, or name)");

  const supabase = getSupabaseAdminClient();

  if (COUNTY_UUID_RE.test(trimmed)) {
    const { data, error } = await supabase.from("counties").select("id").eq("id", trimmed).maybeSingle();
    if (error) throw error;
    if (!data) throw new Error(`No county found for id "${trimmed}"`);
    return data.id;
  }

  const slugNormalized = trimmed
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "");

  if (slugNormalized) {
    const { data: bySlugNorm } = await supabase
      .from("counties")
      .select("id")
      .eq("slug", slugNormalized)
      .maybeSingle();
    if (bySlugNorm) return bySlugNorm.id;
  }

  const { data: bySlugRaw } = await supabase
    .from("counties")
    .select("id")
    .eq("slug", trimmed.toLowerCase())
    .maybeSingle();
  if (bySlugRaw) return bySlugRaw.id;

  const safeName = escapeIlikeLiteral(trimmed);
  const { data: byName, error: nameErr } = await supabase.from("counties").select("id, name").ilike("name", safeName);
  if (nameErr) throw nameErr;
  if (!byName?.length) {
    throw new Error(
      `County not found: "${trimmed}". Add a row in Table Editor → counties (slug e.g. san-diego), or paste the county UUID.`
    );
  }
  if (byName.length > 1) {
    throw new Error(`Multiple counties match "${trimmed}" — use slug or UUID`);
  }
  return byName[0].id;
}
