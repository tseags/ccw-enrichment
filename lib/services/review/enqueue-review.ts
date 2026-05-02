import { getSupabaseAdminClient } from "@/lib/db/supabase";
import { reviewItemSchema } from "@/lib/schemas/core";

export async function enqueueReviewItem(input: {
  vendorId: string;
  runId?: string;
  reasonCode: string;
  severity?: "low" | "medium" | "high" | "critical";
  payload?: Record<string, unknown>;
}) {
  const review = reviewItemSchema.parse({
    vendorId: input.vendorId,
    runId: input.runId,
    reasonCode: input.reasonCode,
    severity: input.severity ?? "medium",
    payload: input.payload ?? {}
  });

  const supabase = getSupabaseAdminClient();
  const { data, error } = await supabase
    .from("review_queue")
    .insert({
      vendor_id: review.vendorId,
      run_id: review.runId,
      reason_code: review.reasonCode,
      severity: review.severity,
      payload_json: review.payload
    })
    .select("*")
    .single();
  if (error) throw error;
  return data;
}
