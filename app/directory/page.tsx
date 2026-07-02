import { getDirectoryVendorGroups } from "@/lib/db/carry-class-queries";

export const revalidate = 3600;

export default async function DirectoryPage() {
  const result = await getDirectoryVendorGroups();

  if (!result.ok) {
    return (
      <section className="space-y-3 rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
        <h2 className="text-lg font-semibold">Directory not available</h2>
        <p>Supabase returned an error (often missing table before migrations through 0006 are applied):</p>
        <pre className="overflow-x-auto rounded bg-white p-2 text-xs">{result.error}</pre>
        <p className="text-slate-700">
          Apply repo migrations in the Supabase SQL editor or CLI (through{" "}
          <code className="rounded bg-white px-1">0006_rename_enriched_vendor_to_carry_class_vendor_data.sql</code>), then run{" "}
          <code className="rounded bg-white px-1">npm run db:load-enriched</code>.
        </p>
      </section>
    );
  }

  const groups = result.groups;

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Public directory (enriched CSV)</h2>
        <p className="mt-1 text-sm text-slate-600">
          One card per vendor. Counties served are aggregated; each county row may have its own phone, email, or website.
        </p>
      </div>

      {groups.length === 0 ? (
        <p className="text-sm text-slate-600">No rows yet. Apply migrations through 0006, then run npm run db:load-enriched.</p>
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
