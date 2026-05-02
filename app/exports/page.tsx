"use client";

import { useState } from "react";

export default function ExportsPage() {
  const [message, setMessage] = useState("");

  async function runSheetsSync() {
    const res = await fetch("/api/export/sheets", { method: "POST" });
    const data = await res.json();
    setMessage(res.ok ? `Synced ${data.rows} rows to sheets` : data.error);
  }

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Export / Sync</h2>
      <div className="space-y-3 rounded border bg-white p-4">
        <a href="/api/export/csv" className="inline-block rounded bg-slate-900 px-4 py-2 text-sm text-white">
          Download CSV
        </a>
        <div>
          <button onClick={runSheetsSync} className="rounded border px-4 py-2 text-sm">
            Sync To Google Sheets
          </button>
        </div>
        {message ? <p className="text-sm">{message}</p> : null}
      </div>
    </section>
  );
}
