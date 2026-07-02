import { ConfidencePill } from "@/components/confidence-pill";
import { StatusBadge } from "@/components/status-badge";
import { getVendorListRows } from "@/lib/db/carry-class-queries";

/** Ops admin table — 5 min cache; use /api/export/csv for a fresh full dump. */
export const revalidate = 300;

function confidenceCell(raw: string | null) {
  if (raw == null || raw === "") return <span className="text-slate-500">N/A</span>;
  const n = Number.parseFloat(raw.replace(/%/g, "").trim());
  if (!Number.isNaN(n) && n >= 0 && n <= 1) {
    return <ConfidencePill confidence={n} />;
  }
  if (!Number.isNaN(n) && n > 1 && n <= 100) {
    return <ConfidencePill confidence={n / 100} />;
  }
  return <span className="text-xs text-slate-700">{raw}</span>;
}

export default async function VendorsPage() {
  const result = await getVendorListRows();
  const rows = result.ok ? result.rows : [];

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Vendor data (carry_class_vendor_data)</h2>
      <p className="text-sm text-slate-600">
        One row per vendor listing per county, synced from the enriched CSV pipeline (same source as Directory).
      </p>
      {!result.ok ? (
        <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">{result.error}</p>
      ) : null}
      <div className="overflow-hidden rounded border bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-100">
            <tr>
              <th className="px-3 py-2">Vendor</th>
              <th className="px-3 py-2">County</th>
              <th className="px-3 py-2">Website</th>
              <th className="px-3 py-2">Location</th>
              <th className="px-3 py-2">Crawl</th>
              <th className="px-3 py-2">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t">
                <td className="px-3 py-2">{row.vendor_name}</td>
                <td className="px-3 py-2 capitalize">{row.county.replace(/-/g, " ")}</td>
                <td className="max-w-[200px] truncate px-3 py-2">
                  {row.website_url ? (
                    <a className="text-blue-700 underline" href={row.website_url} target="_blank" rel="noreferrer">
                      {row.website_url}
                    </a>
                  ) : (
                    "N/A"
                  )}
                </td>
                <td className="px-3 py-2">
                  {[row.city, row.state].filter(Boolean).join(", ") || "N/A"}
                </td>
                <td className="px-3 py-2">
                  {row.crawl_status ? <StatusBadge label={row.crawl_status} /> : <span className="text-slate-500">N/A</span>}
                </td>
                <td className="px-3 py-2">{confidenceCell(row.enrichment_confidence)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
