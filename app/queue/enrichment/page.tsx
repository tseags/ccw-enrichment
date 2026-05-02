import { getSupabaseAdminClient } from "@/lib/db/supabase";
import { StatusBadge } from "@/components/status-badge";
import { RunEnrichmentButton } from "@/components/run-enrichment-button";
import { EnqueueCountyButton } from "@/components/enqueue-county-button";
import Link from "next/link";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function EnrichmentQueuePage({ searchParams }: Props) {
  const params = await searchParams;
  const countyFilter = typeof params.county === "string" ? params.county : "";
  const pageParam = typeof params.page === "string" ? Number(params.page) : 1;
  const page = Number.isFinite(pageParam) && pageParam >= 1 ? pageParam : 1;

  const supabase = getSupabaseAdminClient();

  const { data: counties } = await supabase.from("counties").select("id, name, slug").order("name");

  const selectedCounty = countyFilter
    ? (counties ?? []).find((c) => c.slug === countyFilter || c.id === countyFilter)
    : null;

  let query = supabase
    .from("vendors")
    .select("id, canonical_name, status, website_url, last_enriched_at", { count: "exact" })
    .in("status", ["new", "ready_for_enrichment", "needs_review"])
    .order("created_at", { ascending: false })
    .range((page - 1) * PAGE_SIZE, page * PAGE_SIZE - 1);

  if (selectedCounty) {
    const { data: listings } = await supabase
      .from("vendor_county_listings")
      .select("vendor_id")
      .eq("county_id", selectedCounty.id);
    const vendorIds = (listings ?? []).map((l) => l.vendor_id);
    if (vendorIds.length > 0) {
      query = query.in("id", vendorIds);
    } else {
      query = query.eq("id", "00000000-0000-0000-0000-000000000000");
    }
  }

  const { data: vendors, count } = await query;
  const totalPages = Math.max(1, Math.ceil((count ?? 0) / PAGE_SIZE));

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">Enrichment Queue</h2>
        {selectedCounty && (
          <EnqueueCountyButton countyId={selectedCounty.id} countyName={selectedCounty.name} />
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <Link
          href="/queue/enrichment"
          className={`rounded border px-3 py-1 ${!countyFilter ? "bg-slate-900 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}`}
        >
          All
        </Link>
        {(counties ?? []).map((c) => (
          <Link
            key={c.id}
            href={`/queue/enrichment?county=${c.slug}`}
            className={`rounded border px-3 py-1 ${countyFilter === c.slug ? "bg-slate-900 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}`}
          >
            {c.name}
          </Link>
        ))}
      </div>

      <p className="text-xs text-slate-500">
        {count ?? 0} vendor{(count ?? 0) === 1 ? "" : "s"} pending — page {page} of {totalPages}
      </p>

      <div className="overflow-hidden rounded border bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-100">
            <tr>
              <th className="px-3 py-2">Vendor</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Website</th>
              <th className="px-3 py-2">Action</th>
            </tr>
          </thead>
          <tbody>
            {(vendors ?? []).map((vendor) => (
              <tr key={vendor.id} className="border-t">
                <td className="px-3 py-2">{vendor.canonical_name}</td>
                <td className="px-3 py-2">
                  <StatusBadge label={vendor.status} />
                </td>
                <td className="px-3 py-2 max-w-xs truncate">{vendor.website_url ?? "N/A"}</td>
                <td className="px-3 py-2">
                  <RunEnrichmentButton vendorId={vendor.id} />
                </td>
              </tr>
            ))}
            {(vendors ?? []).length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-center text-slate-400">
                  No pending vendors{selectedCounty ? ` for ${selectedCounty.name}` : ""}.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center gap-2 text-sm">
          {page > 1 && (
            <Link
              href={`/queue/enrichment?${countyFilter ? `county=${countyFilter}&` : ""}page=${page - 1}`}
              className="rounded border bg-white px-3 py-1 hover:bg-slate-50"
            >
              ← Prev
            </Link>
          )}
          {page < totalPages && (
            <Link
              href={`/queue/enrichment?${countyFilter ? `county=${countyFilter}&` : ""}page=${page + 1}`}
              className="rounded border bg-white px-3 py-1 hover:bg-slate-50"
            >
              Next →
            </Link>
          )}
        </div>
      )}
    </section>
  );
}
