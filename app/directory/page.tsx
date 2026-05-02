import { getSupabaseAdminClient } from "@/lib/db/supabase";

export const dynamic = "force-dynamic";

type EnrichedListing = {
  id: string;
  county: string;
  needs_review: string | null;
  vendor_name: string;
  instructor_names: string | null;
  email: string | null;
  phone: string | null;
  website_url: string | null;
  booking_capability: string | null;
  city: string | null;
  state: string | null;
  address: string | null;
  price_16hr_full: string | null;
  price_8hr_renewal: string | null;
  price_add_a_gun: string | null;
  vendor_description: string | null;
  crawl_status: string | null;
  enrichment_confidence: string | null;
  normalized_vendor_name: string | null;
};

function groupByVendor(rows: EnrichedListing[]) {
  const map = new Map<string, EnrichedListing[]>();
  for (const r of rows) {
    const key = r.normalized_vendor_name ?? r.vendor_name.trim().toLowerCase();
    const list = map.get(key) ?? [];
    list.push(r);
    map.set(key, list);
  }
  for (const list of map.values()) {
    list.sort((a, b) => a.county.localeCompare(b.county));
  }
  return [...map.entries()].sort((a, b) =>
    (a[1][0]?.vendor_name ?? "").localeCompare(b[1][0]?.vendor_name ?? "", undefined, { sensitivity: "base" })
  );
}

export default async function DirectoryPage() {
  const supabase = getSupabaseAdminClient();
  const { data, error } = await supabase
    .from("enriched_vendor_county_listings")
    .select(
      "id, county, needs_review, vendor_name, instructor_names, email, phone, website_url, booking_capability, city, state, address, price_16hr_full, price_8hr_renewal, price_add_a_gun, vendor_description, crawl_status, enrichment_confidence, normalized_vendor_name"
    )
    .order("vendor_name", { ascending: true })
    .order("county", { ascending: true });

  if (error) {
    return (
      <section className="space-y-3 rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
        <h2 className="text-lg font-semibold">Directory not available</h2>
        <p>Supabase returned an error (often missing table before migration 0004 is applied):</p>
        <pre className="overflow-x-auto rounded bg-white p-2 text-xs">{error.message}</pre>
        <p className="text-slate-700">
          Apply <code className="rounded bg-white px-1">supabase/migrations/0004_enriched_vendor_county_listings.sql</code> in the
          Supabase SQL editor or CLI, then run <code className="rounded bg-white px-1">npm run db:load-enriched</code>.
        </p>
      </section>
    );
  }

  const rows = (data ?? []) as EnrichedListing[];
  const groups = groupByVendor(rows);

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Public directory (enriched CSV)</h2>
        <p className="mt-1 text-sm text-slate-600">
          One card per vendor. Counties served are aggregated; each county row may have its own phone, email, or website.
        </p>
      </div>

      {groups.length === 0 ? (
        <p className="text-sm text-slate-600">No rows yet. Run migration 0004, then run npm run db:load-enriched.</p>
      ) : (
        <ul className="space-y-6">
          {groups.map(([key, listings]) => {
            const title = listings[0]?.vendor_name ?? key;
            const counties = [...new Set(listings.map((l) => l.county))].sort((a, b) => a.localeCompare(b));
            const bestDesc = listings.reduce(
              (best, l) => (l.vendor_description && l.vendor_description.length > (best?.length ?? 0) ? l.vendor_description : best),
              null as string | null
            );
            return (
              <li key={key} className="overflow-hidden rounded-lg border bg-white shadow-sm">
                <div className="grid gap-4 p-4 md:grid-cols-[1fr_280px] md:gap-6">
                  <div className="space-y-3">
                    <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
                    <div>
                      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Counties served</p>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {counties.map((c) => (
                          <span key={c} className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-800">
                            {c.replace(/-/g, " ")}
                          </span>
                        ))}
                      </div>
                    </div>
                    {bestDesc ? (
                      <p className="text-sm leading-relaxed text-slate-700">{bestDesc}</p>
                    ) : (
                      <p className="text-sm text-slate-500">No description.</p>
                    )}
                  </div>
                  <aside className="border-t border-slate-100 pt-4 md:border-l md:border-t-0 md:pl-6 md:pt-0">
                    <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Contact by county</p>
                    <ul className="mt-2 space-y-3 text-sm">
                      {listings.map((l) => (
                        <li key={l.id} className="rounded border border-slate-100 bg-slate-50/80 p-2.5">
                          <p className="font-medium capitalize text-slate-900">{l.county.replace(/-/g, " ")}</p>
                          {l.instructor_names ? <p className="text-xs text-slate-600">Instructors: {l.instructor_names}</p> : null}
                          {l.phone ? <p className="mt-1">Phone: {l.phone}</p> : null}
                          {l.email ? <p>Email: {l.email}</p> : null}
                          {l.website_url ? (
                            <p className="truncate">
                              Web:{" "}
                              <a className="text-blue-700 underline" href={l.website_url} target="_blank" rel="noreferrer">
                                {l.website_url}
                              </a>
                            </p>
                          ) : null}
                          {l.city || l.address ? (
                            <p className="text-xs text-slate-600">
                              {[l.city, l.state].filter(Boolean).join(", ")}
                              {l.address ? ` · ${l.address}` : ""}
                            </p>
                          ) : null}
                          {l.needs_review ? (
                            <p className="mt-1 text-xs text-amber-800">Review: {l.needs_review}</p>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </aside>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
