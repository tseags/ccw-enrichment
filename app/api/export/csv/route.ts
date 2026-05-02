import { NextResponse } from "next/server";
import { stringify } from "csv-stringify/sync";
import { getSupabaseAdminClient } from "@/lib/db/supabase";

export async function GET() {
  const supabase = getSupabaseAdminClient();
  const { data: vendors, error } = await supabase
    .from("vendors")
    .select("id, canonical_name, website_url, website_confidence, hq_city, status, last_enriched_at")
    .order("canonical_name");

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const csv = stringify(vendors ?? [], { header: true });
  return new NextResponse(csv, {
    headers: {
      "Content-Type": "text/csv",
      "Content-Disposition": "attachment; filename=\"vendors.csv\""
    }
  });
}
