import { NextResponse } from "next/server";
import { runVendorEnrichment } from "@/lib/pipeline/enrichment-orchestrator";

export async function POST(req: Request) {
  try {
    const body = (await req.json()) as { vendorId: string };
    const runId = await runVendorEnrichment(body.vendorId);
    return NextResponse.json({ runId });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Enrichment failed" },
      { status: 500 }
    );
  }
}
