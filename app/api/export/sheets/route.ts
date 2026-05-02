import { NextResponse } from "next/server";
import { getSupabaseAdminClient } from "@/lib/db/supabase";
import { syncToSheets } from "@/lib/services/export/sync-to-sheets";

export async function POST() {
  try {
    const supabase = getSupabaseAdminClient();
    const { data: vendors, error } = await supabase
      .from("vendors")
      .select("canonical_name, website_url, website_confidence, hq_city, status, last_enriched_at")
      .order("canonical_name");
    if (error) throw error;

    await syncToSheets(vendors ?? []);
    return NextResponse.json({ ok: true, rows: vendors?.length ?? 0 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Sheets sync failed" },
      { status: 500 }
    );
  }
}
