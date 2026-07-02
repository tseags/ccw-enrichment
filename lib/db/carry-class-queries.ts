import { unstable_cache } from "next/cache";
import type { CarryClassVendorDataRow } from "@/lib/db/carry-class-vendor-data";
import { getSupabaseAdminClient } from "@/lib/db/supabase";

export const DIRECTORY_LIST_SELECT = [
  "id",
  "vendor_name",
  "normalized_vendor_name",
  "county",
  "city",
  "state",
  "phone",
  "email",
  "website_url",
  "vendor_description",
  "instructor_names",
  "address",
  "needs_review"
].join(", ");

export type DirectoryListRow = Pick<
  CarryClassVendorDataRow,
  | "id"
  | "vendor_name"
  | "normalized_vendor_name"
  | "county"
  | "city"
  | "state"
  | "phone"
  | "email"
  | "website_url"
  | "vendor_description"
  | "instructor_names"
  | "address"
  | "needs_review"
>;

export const VENDORS_LIST_SELECT = [
  "id",
  "vendor_name",
  "county",
  "website_url",
  "city",
  "state",
  "crawl_status",
  "enrichment_confidence"
].join(", ");

export type VendorsListRow = Pick<
  CarryClassVendorDataRow,
  "id" | "vendor_name" | "county" | "website_url" | "city" | "state" | "crawl_status" | "enrichment_confidence"
>;

export type DirectoryVendorGroup = [string, DirectoryListRow[]];

export type DirectoryQueryResult =
  | { ok: true; groups: DirectoryVendorGroup[] }
  | { ok: false; error: string };

export type VendorsQueryResult = { ok: true; rows: VendorsListRow[] } | { ok: false; error: string };

function asDirectoryListRows(data: unknown): DirectoryListRow[] {
  return (data ?? []) as DirectoryListRow[];
}

function asVendorsListRows(data: unknown): VendorsListRow[] {
  return (data ?? []) as VendorsListRow[];
}

function groupByVendor(rows: DirectoryListRow[]): DirectoryVendorGroup[] {
  const map = new Map<string, DirectoryListRow[]>();
  for (const r of rows) {
    const key = r.normalized_vendor_name ?? r.vendor_name.trim().toLowerCase();
    const list = map.get(key) ?? [];
    list.push(r);
    map.set(key, list);
  }
  for (const list of map.values()) {
    list.sort((a, b) => a.county.localeCompare(b.county));
  }
  return [...map.entries()].sort((a, b) =>
    (a[1][0]?.vendor_name ?? "").localeCompare(b[1][0]?.vendor_name ?? "", undefined, { sensitivity: "base" })
  );
}

async function fetchDirectoryVendorGroups(): Promise<DirectoryQueryResult> {
  const supabase = getSupabaseAdminClient();
  const { data, error } = await supabase
    .from("carry_class_vendor_data")
    .select(DIRECTORY_LIST_SELECT)
    .order("vendor_name", { ascending: true })
    .order("county", { ascending: true });

  if (error) {
    return { ok: false, error: error.message };
  }

  return { ok: true, groups: groupByVendor(asDirectoryListRows(data)) };
}

async function fetchVendorListRows(): Promise<VendorsQueryResult> {
  const supabase = getSupabaseAdminClient();
  const { data, error } = await supabase
    .from("carry_class_vendor_data")
    .select(VENDORS_LIST_SELECT)
    .order("vendor_name", { ascending: true })
    .order("county", { ascending: true });

  if (error) {
    return { ok: false, error: error.message };
  }

  return { ok: true, rows: asVendorsListRows(data) };
}

export async function getDirectoryVendorGroups(): Promise<DirectoryQueryResult> {
  return unstable_cache(fetchDirectoryVendorGroups, ["carry-class-directory-vendor-groups"], {
    revalidate: 3600,
    tags: ["carry-class-vendor-data"]
  })();
}

export async function getVendorListRows(): Promise<VendorsQueryResult> {
  return unstable_cache(fetchVendorListRows, ["carry-class-vendor-list"], {
    revalidate: 300,
    tags: ["carry-class-vendor-data"]
  })();
}
