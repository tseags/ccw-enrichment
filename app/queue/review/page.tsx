import { ConfidencePill } from "@/components/confidence-pill";
import { StatusBadge } from "@/components/status-badge";
import { getSupabaseAdminClient } from "@/lib/db/supabase";

export const dynamic = "force-dynamic";

export default async function ReviewQueuePage() {
  const supabase = getSupabaseAdminClient();
  const { data: items } = await supabase
    .from("review_queue")
    .select("id, reason_code, severity, status, payload_json, vendors(canonical_name)")
    .in("status", ["open", "in_review"])
    .order("created_at", { ascending: false })
    .limit(200);

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Review Queue</h2>
      <div className="space-y-2">
        {(items ?? []).map((item) => (
          <article key={item.id} className="rounded border bg-white p-3">
            <div className="mb-2 flex items-center gap-2">
              <strong>{(item.vendors as { canonical_name?: string } | null)?.canonical_name ?? "Vendor"}</strong>
              <StatusBadge label={item.status} />
              <StatusBadge label={item.severity} />
            </div>
            <p className="text-sm">Reason: {item.reason_code}</p>
            <pre className="mt-2 overflow-auto rounded bg-slate-50 p-2 text-xs">
              {JSON.stringify(item.payload_json, null, 2)}
            </pre>
            <div className="mt-2">
              <ConfidencePill confidence={0.55} />
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
