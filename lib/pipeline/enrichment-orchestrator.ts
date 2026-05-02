import { getSupabaseAdminClient } from "@/lib/db/supabase";
import { crawlVendorSite } from "@/lib/services/crawl/crawl-vendor-site";
import { scoreWebsiteConfidence, needsReview } from "@/lib/services/confidence/compute-confidence";
import { saveEvidence } from "@/lib/services/evidence/save-evidence";
import { extractPricing } from "@/lib/services/extraction/extract-pricing";
import { detectBookingCapability } from "@/lib/services/extraction/detect-booking-capability";
import { enqueueReviewItem } from "@/lib/services/review/enqueue-review";

/**
 * Core enrichment logic for a single vendor within an existing run.
 * Shared by the API route (ad-hoc) and the worker (batch).
 */
export async function enrichVendor(vendorId: string, runId: string) {
  const supabase = getSupabaseAdminClient();
  const { data: vendor, error } = await supabase.from("vendors").select("*").eq("id", vendorId).single();
  if (error) throw error;

  if (!vendor.website_url) {
    await enqueueReviewItem({
      vendorId,
      runId,
      reasonCode: "no_website_found",
      severity: "high",
      payload: { canonicalName: vendor.canonical_name }
    });
    return;
  }

  const websiteConfidence = scoreWebsiteConfidence({
    emailDomainMatches: true,
    phoneMatchesCountySource: false,
    hasConflictingCandidates: false
  });

  const crawl = await crawlVendorSite({ vendorId, runId, url: vendor.website_url });
  const sourceUrl = crawl.finalUrl ?? crawl.url;
  const pricing = extractPricing({ vendorId, runId, sourceUrl, text: crawl.extractedText });
  const booking = detectBookingCapability({ vendorId, runId, sourceUrl, text: crawl.extractedText });

  await saveEvidence({
    vendorId,
    runId,
    fieldKey: "booking_capability",
    valueText: booking.bookingCapability,
    sourceUrl: booking.sourceUrl,
    sourceType: "webpage",
    evidenceSnippet: booking.evidenceSnippet,
    confidence: booking.confidence,
    extractorType: "deterministic"
  });

  for (const price of pricing.prices) {
    await saveEvidence({
      vendorId,
      runId,
      fieldKey: price.courseType,
      valueText: String(price.priceCents),
      sourceUrl: price.sourceUrl,
      sourceType: "webpage",
      evidenceSnippet: price.evidenceSnippet,
      confidence: price.confidence,
      extractorType: "deterministic"
    });
  }

  if (needsReview(websiteConfidence.score, false) || booking.confidence < 0.6 || pricing.prices.length === 0) {
    await enqueueReviewItem({
      vendorId,
      runId,
      reasonCode: "low_confidence_enrichment",
      severity: "medium",
      payload: {
        websiteConfidence: websiteConfidence.score,
        websiteReasons: websiteConfidence.reasons,
        bookingConfidence: booking.confidence,
        extractedPriceCount: pricing.prices.length
      }
    });
  }

  await supabase
    .from("vendors")
    .update({
      website_confidence: websiteConfidence.score,
      status: "enriched",
      last_enriched_at: new Date().toISOString()
    })
    .eq("id", vendorId);
}

/**
 * Ad-hoc single-vendor enrichment (creates its own run).
 * Used by the existing POST /api/enrichment/run route.
 */
export async function runVendorEnrichment(vendorId: string) {
  const supabase = getSupabaseAdminClient();

  const { data: run, error: runError } = await supabase
    .from("enrichment_runs")
    .insert({ trigger_type: "manual", scope_type: "vendor", scope_ref: vendorId, status: "running", started_at: new Date().toISOString() })
    .select("*")
    .single();
  if (runError) throw runError;

  try {
    await enrichVendor(vendorId, run.id);

    await supabase
      .from("enrichment_runs")
      .update({ status: "completed", completed_at: new Date().toISOString() })
      .eq("id", run.id);
    return run.id;
  } catch (e) {
    await supabase
      .from("enrichment_runs")
      .update({
        status: "failed",
        completed_at: new Date().toISOString(),
        error_summary: e instanceof Error ? e.message : "Unknown error"
      })
      .eq("id", run.id);
    throw e;
  }
}
