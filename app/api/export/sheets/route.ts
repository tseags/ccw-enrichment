import { NextResponse } from "next/server";
import {
  asCarryClassVendorRows,
  CARRY_CLASS_VENDOR_DATA_COLUMNS,
  CARRY_CLASS_VENDOR_DATA_SELECT
} from "@/lib/db/carry-class-vendor-data";
import { getSupabaseAdminClient } from "@/lib/db/supabase";
import { syncToSheets } from "@/lib/services/export/sync-to-sheets";

export async function POST() {
  try {
    const supabase = getSupabaseAdminClient();
    const { data: rows, error } = await supabase
      .from("carry_class_vendor_data")
      .select(CARRY_CLASS_VENDOR_DATA_SELECT)
      .order("vendor_name", { ascending: true })
      .order("county", { ascending: true });
    if (error) throw error;

    const list = asCarryClassVendorRows(rows);
    const ordered = list.map((r) => {
      const rec: Record<string, string | number | null> = {};
      for (const col of CARRY_CLASS_VENDOR_DATA_COLUMNS) {
        const v = r[col];
        if (v === null || v === undefined) rec[col] = null;
        else if (typeof v === "string" || typeof v === "number") rec[col] = v;
        else rec[col] = String(v);
      }
      return rec;
    });

    await syncToSheets(ordered);
    return NextResponse.json({ ok: true, rows: ordered.length });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Sheets sync failed" },
      { status: 500 }
    );
  }
}
