import { websiteResolutionResultSchema } from "@/lib/schemas/core";
import type { NormalizedVendor } from "@/lib/types";

export function resolveOfficialWebsite(vendor: NormalizedVendor) {
  const candidates = vendor.websiteUrl
    ? [{ url: vendor.websiteUrl, score: 0.92, reasons: ["listed_in_county_source"] }]
    : [];

  return websiteResolutionResultSchema.parse({
    vendorId: crypto.randomUUID(),
    selectedUrl: candidates[0]?.url,
    confidence: candidates[0]?.score ?? 0.2,
    decisionSummary: candidates.length > 0 ? "Used source-listed website." : "No website candidate found.",
    candidates
  });
}
