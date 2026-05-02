import { getSupabaseAdminClient } from "@/lib/db/supabase";
import { vendorFieldEvidenceSchema } from "@/lib/schemas/core";

export async function saveEvidence(input: {
  vendorId: string;
  runId: string;
  fieldKey: string;
  valueText?: string;
  sourceUrl: string;
  sourceType: "pdf" | "webpage" | "manual";
  evidenceSnippet: string;
  confidence: number;
  extractorType: "deterministic" | "ai";
}) {
  const evidence = vendorFieldEvidenceSchema.parse({
    ...input,
    extractedAt: new Date().toISOString()
  });

  const supabase = getSupabaseAdminClient();
  const { data, error } = await supabase
    .from("vendor_field_evidence")
    .insert({
      vendor_id: evidence.vendorId,
      run_id: evidence.runId,
      field_key: evidence.fieldKey,
      value_text: evidence.valueText,
      source_url: evidence.sourceUrl,
      source_type: evidence.sourceType,
      evidence_snippet: evidence.evidenceSnippet,
      confidence: evidence.confidence,
      extractor_type: evidence.extractorType,
      extracted_at: evidence.extractedAt
    })
    .select("*")
    .single();
  if (error) throw error;
  return data;
}
