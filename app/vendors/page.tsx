import { ConfidencePill } from "@/components/confidence-pill";
import { StatusBadge } from "@/components/status-badge";
import { getSupabaseAdminClient } from "@/lib/db/supabase";

export const dynamic = "force-dynamic";

export default async function VendorsPage() {
  const supabase = getSupabaseAdminClient();
  const { data: vendors } = await supabase
    .from("vendors")
    .select("id, canonical_name, website_url, website_confidence, hq_city, status, last_enriched_at")
    .order("canonical_name");

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Vendor Database</h2>
      <div className="overflow-hidden rounded border bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-100">
            <tr>
              <th className="px-3 py-2">Vendor</th>
              <th className="px-3 py-2">Website</th>
              <th className="px-3 py-2">Location</th>
              <th className="px-3 py-2">Confidence</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {(vendors ?? []).map((vendor) => (
              <tr key={vendor.id} className="border-t">
                <td className="px-3 py-2">{vendor.canonical_name}</td>
                <td className="px-3 py-2">{vendor.website_url ?? "N/A"}</td>
                <td className="px-3 py-2">{vendor.hq_city ?? "N/A"}</td>
                <td className="px-3 py-2">
                  <ConfidencePill confidence={vendor.website_confidence ?? 0} />
                </td>
                <td className="px-3 py-2">
                  <StatusBadge label={vendor.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
