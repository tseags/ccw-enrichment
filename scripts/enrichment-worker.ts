/**
 * Enrichment worker — polls Supabase for queued enrichment_jobs, runs them
 * with global concurrency control, and marks them completed/failed.
 *
 * Usage:
 *   npm run worker          (uses .env.local by default)
 *   ENRICHMENT_GLOBAL_CONCURRENCY=5 npm run worker
 *
 * Ctrl-C for graceful shutdown.
 */

import { env } from "@/lib/env";
import { getSupabaseAdminClient } from "@/lib/db/supabase";
import { enrichVendor } from "@/lib/pipeline/enrichment-orchestrator";
import pLimit from "p-limit";

const supabase = getSupabaseAdminClient();
const globalLimit = pLimit(env.ENRICHMENT_GLOBAL_CONCURRENCY);

let shuttingDown = false;

type EnrichmentJob = {
  id: string;
  run_id: string;
  vendor_id: string;
  attempts: number;
  max_attempts: number;
};

async function claimJobs(batchSize: number): Promise<EnrichmentJob[]> {
  const { data, error } = await supabase.rpc("claim_enrichment_jobs", { batch_size: batchSize });
  if (error) {
    console.error("[worker] claim error:", error.message);
    return [];
  }
  return (data ?? []) as EnrichmentJob[];
}

async function markCompleted(jobId: string) {
  await supabase
    .from("enrichment_jobs")
    .update({ status: "completed", completed_at: new Date().toISOString() })
    .eq("id", jobId);
}

async function markFailed(jobId: string, errorMsg: string, requeue: boolean) {
  if (requeue) {
    await supabase
      .from("enrichment_jobs")
      .update({ status: "queued", error_summary: errorMsg, claimed_at: null })
      .eq("id", jobId);
  } else {
    await supabase
      .from("enrichment_jobs")
      .update({ status: "failed", completed_at: new Date().toISOString(), error_summary: errorMsg })
      .eq("id", jobId);
  }
}

async function processJob(job: EnrichmentJob) {
  const t0 = Date.now();
  const tag = `[vendor=${job.vendor_id.slice(0, 8)} run=${job.run_id.slice(0, 8)} attempt=${job.attempts}]`;
  console.log(`${tag} starting`);

  try {
    await enrichVendor(job.vendor_id, job.run_id);
    await markCompleted(job.id);
    console.log(`${tag} completed in ${Date.now() - t0}ms`);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    const canRetry = job.attempts < job.max_attempts;
    await markFailed(job.id, msg, canRetry);
    console.error(`${tag} failed (${canRetry ? "will retry" : "giving up"}): ${msg}`);
  }
}

async function pollLoop() {
  console.log(
    `[worker] started — concurrency=${env.ENRICHMENT_GLOBAL_CONCURRENCY}` +
      ` perHost=${env.ENRICHMENT_PER_HOST_CONCURRENCY}` +
      ` delay=${env.ENRICHMENT_REQUEST_DELAY_MS}ms` +
      ` poll=${env.ENRICHMENT_POLL_INTERVAL_S}s`
  );

  while (!shuttingDown) {
    const available = globalLimit.pendingCount === 0 ? env.ENRICHMENT_GLOBAL_CONCURRENCY - globalLimit.activeCount : 0;
    if (available <= 0) {
      await sleep(1_000);
      continue;
    }

    const jobs = await claimJobs(available);

    if (jobs.length === 0) {
      await sleep(env.ENRICHMENT_POLL_INTERVAL_S * 1_000);
      continue;
    }

    for (const job of jobs) {
      if (shuttingDown) break;
      globalLimit(() => processJob(job));
    }
  }

  console.log("[worker] waiting for in-flight jobs to finish...");
  while (globalLimit.activeCount > 0) {
    await sleep(500);
  }
  console.log("[worker] shut down cleanly");
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

process.on("SIGINT", () => {
  console.log("\n[worker] SIGINT received, shutting down...");
  shuttingDown = true;
});
process.on("SIGTERM", () => {
  console.log("[worker] SIGTERM received, shutting down...");
  shuttingDown = true;
});

pollLoop().catch((err) => {
  console.error("[worker] fatal:", err);
  process.exit(1);
});
