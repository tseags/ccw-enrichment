import { pricingExtractionResultSchema } from "@/lib/schemas/core";

const coursePatterns = [
  { courseType: "initial_16hr_day1", pattern: /day\s*1.{0,40}\$(\d+(?:\.\d{2})?)/i },
  { courseType: "initial_16hr_day2", pattern: /day\s*2.{0,40}\$(\d+(?:\.\d{2})?)/i },
  { courseType: "initial_16hr_full", pattern: /16\s*hr.{0,40}\$(\d+(?:\.\d{2})?)/i },
  { courseType: "renewal_8hr", pattern: /8\s*hr.{0,40}\$(\d+(?:\.\d{2})?)/i }
] as const;

export function extractPricing(params: { vendorId: string; runId: string; sourceUrl: string; text: string }) {
  const prices = coursePatterns
    .map(({ courseType, pattern }) => {
      const match = params.text.match(pattern);
      if (!match) return null;
      const amount = Math.round(Number.parseFloat(match[1]) * 100);
      return {
        courseType,
        priceCents: amount,
        currency: "USD",
        sourceUrl: params.sourceUrl,
        evidenceSnippet: match[0],
        confidence: 0.8
      };
    })
    .filter((value): value is NonNullable<typeof value> => Boolean(value));

  return pricingExtractionResultSchema.parse({
    vendorId: params.vendorId,
    runId: params.runId,
    prices
  });
}
