import { z } from "zod";
import {
  bookingClassificationResultSchema,
  enrichmentStatusSchema,
  normalizedVendorSchema,
  pageCrawlResultSchema,
  pricingExtractionResultSchema,
  rawCountyVendorRowSchema,
  reviewItemSchema,
  vendorFieldEvidenceSchema,
  websiteResolutionResultSchema
} from "@/lib/schemas/core";

export type RawCountyVendorRow = z.infer<typeof rawCountyVendorRowSchema>;
export type NormalizedVendor = z.infer<typeof normalizedVendorSchema>;
export type WebsiteResolutionResult = z.infer<typeof websiteResolutionResultSchema>;
export type PageCrawlResult = z.infer<typeof pageCrawlResultSchema>;
export type PricingExtractionResult = z.infer<typeof pricingExtractionResultSchema>;
export type BookingClassificationResult = z.infer<typeof bookingClassificationResultSchema>;
export type EnrichmentStatus = z.infer<typeof enrichmentStatusSchema>;
export type ReviewItem = z.infer<typeof reviewItemSchema>;
export type VendorFieldEvidence = z.infer<typeof vendorFieldEvidenceSchema>;
