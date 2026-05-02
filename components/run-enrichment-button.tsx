"use client";

import { useState } from "react";

export function RunEnrichmentButton({ vendorId }: { vendorId: string }) {
  const [status, setStatus] = useState<"idle" | "running" | "done" | "error">("idle");

  async function run() {
    setStatus("running");
    const res = await fetch("/api/enrichment/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vendorId })
    });
    setStatus(res.ok ? "done" : "error");
  }

  return (
    <button onClick={run} className="rounded bg-slate-900 px-3 py-1 text-white">
      {status === "running" ? "Running..." : status === "done" ? "Done" : status === "error" ? "Retry" : "Run"}
    </button>
  );
}
