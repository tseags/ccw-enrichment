import { NextResponse } from "next/server";
import { getSupabaseAdminClient } from "@/lib/db/supabase";

export async function POST(req: Request) {
  try {
    const body = (await req.json()) as {
      reviewItemId: string;
      actionType: "approve" | "edit" | "reject" | "dismiss";
      actor?: string;
      before?: Record<string, unknown>;
      after?: Record<string, unknown>;
    };

    const supabase = getSupabaseAdminClient();
    const status = body.actionType === "dismiss" ? "dismissed" : "resolved";

    await supabase.from("review_actions").insert({
      review_item_id: body.reviewItemId,
      action_type: body.actionType,
      before_json: body.before ?? null,
      after_json: body.after ?? null,
      actor: body.actor ?? "admin"
    });

    await supabase
      .from("review_queue")
      .update({
        status,
        resolved_at: new Date().toISOString()
      })
      .eq("id", body.reviewItemId);

    return NextResponse.json({ ok: true });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Review action failed" },
      { status: 500 }
    );
  }
}
