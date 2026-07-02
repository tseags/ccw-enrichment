import { NextResponse } from "next/server";
import { stringify } from "csv-stringify/sync";
import {
  CARRY_CLASS_VENDOR_DATA_COLUMNS,
  CARRY_CLASS_VENDOR_DATA_SELECT
} from "@/lib/db/carry-class-vendor-data";
import { getSupabaseAdminClient } from "@/lib/db/supabase";

export async function GET() {
  const supabase = getSupabaseAdminClient();
  const { data: rows, error } = await supabase
    .from("carry_class_vendor_data")
    .select(CARRY_CLASS_VENDOR_DATA_SELECT)
    .order("vendor_name", { ascending: true })
    .order("county", { ascending: true });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const csv = stringify(rows ?? [], {
    header: true,
    columns: [...CARRY_CLASS_VENDOR_DATA_COLUMNS]
  });
  return new NextResponse(csv, {
    headers: {
      "Content-Type": "text/csv",
      "Content-Disposition": "attachment; filename=\"carry-class-vendor-data.csv\""
    }
  });
}
