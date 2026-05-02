"use client";

import { useState } from "react";

export function EnqueueCountyButton({ countyId, countyName }: { countyId: string; countyName: string }) {
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [result, setResult] = useState("");

  async function enqueue() {
    setStatus("loading");
    setResult("");
    try {
      const res = await fetch("/api/enrichment/enqueue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ countyId })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Enqueue failed");
      setResult(`Enqueued ${data.jobsEnqueued} vendors`);
      setStatus("done");
    } catch (err) {
      setResult(err instanceof Error ? err.message : "Error");
      setStatus("error");
    }
  }

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={enqueue}
        disabled={status === "loading"}
        className="rounded bg-indigo-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-800 disabled:opacity-50"
      >
        {status === "loading" ? "Enqueuing…" : `Enqueue ${countyName}`}
      </button>
      {result && (
        <span className={`text-sm ${status === "error" ? "text-red-600" : "text-emerald-700"}`}>{result}</span>
      )}
    </div>
  );
}
