import { NextResponse } from "next/server";
import { resolveCountyId } from "@/lib/db/repositories";
import { getSupabaseAdminClient } from "@/lib/db/supabase";

export async function POST(req: Request) {
  try {
    const body = (await req.json()) as { county?: string; countyId?: string };
    const raw = (body.county ?? body.countyId ?? "").trim();
    if (!raw) {
      return NextResponse.json({ error: "county is required (name, slug, or UUID)" }, { status: 400 });
    }

    const countyId = await resolveCountyId(raw);
    const supabase = getSupabaseAdminClient();

    const { data: run, error: runErr } = await supabase
      .from("enrichment_runs")
      .insert({
        trigger_type: "batch",
        scope_type: "county",
        scope_ref: countyId,
        status: "queued"
      })
      .select("*")
      .single();
    if (runErr) throw runErr;

    const { data: enqueued, error: enqErr } = await supabase.rpc("enqueue_county_vendors", {
      p_run_id: run.id,
      p_county_id: countyId,
      p_max_attempts: 3
    });
    if (enqErr) throw enqErr;

    return NextResponse.json({ runId: run.id, countyId, jobsEnqueued: enqueued });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Enqueue failed" },
      { status: 500 }
    );
  }
}
