import { z } from "zod";
import {
  bookingCapabilitySchema,
  courseTypeSchema,
  enrichmentStageSchema,
  reviewSeveritySchema,
  reviewStatusSchema,
  sourceTypeSchema,
  stageStatusSchema
} from "@/lib/schemas/enums";

const confidenceSchema = z.number().min(0).max(1);

export const rawCountyVendorRowSchema = z.object({
  countyId: z.string().uuid(),
  countySourceId: z.string().uuid(),
  rowIndex: z.number().int().nonnegative(),
  rawText: z.string().min(1),
  parsedName: z.string().optional(),
  parsedContacts: z.array(z.string()).default([]),
  parsedEmails: z.array(z.string().email()).default([]),
  parsedPhones: z.array(z.string()).default([]),
  parsedCity: z.string().optional(),
  parsedWebsite: z.string().url().optional(),
  parseConfidence: confidenceSchema.default(0.5),
  parseWarnings: z.array(z.string()).default([])
});

export const normalizedVendorSchema = z.object({
  canonicalName: z.string().min(1),
  normalizedName: z.string().min(1),
  websiteUrl: z.string().url().optional(),
  hqCity: z.string().optional(),
  contacts: z
    .array(
      z.object({
        name: z.string().optional(),
        role: z.string().optional(),
        email: z.string().email().optional(),
        phone: z.string().optional(),
        isPrimary: z.boolean().default(false)
      })
    )
    .default([])
});

export const websiteResolutionResultSchema = z.object({
  vendorId: z.string().uuid(),
  selectedUrl: z.string().url().optional(),
  confidence: confidenceSchema,
  decisionSummary: z.string(),
  candidates: z.array(
    z.object({
      url: z.string().url(),
      score: z.number(),
      reasons: z.array(z.string()).default([])
    })
  )
});

export const pageCrawlResultSchema = z.object({
  vendorId: z.string().uuid(),
  runId: z.string().uuid(),
  url: z.string().url(),
  finalUrl: z.string().url().optional(),
  sourceType: sourceTypeSchema.default("webpage"),
  retrievalMethod: z.enum(["http", "playwright"]),
  httpStatus: z.number().int().optional(),
  pageTitle: z.string().optional(),
  extractedText: z.string().default(""),
  fetchedAt: z.string().datetime()
});

export const pricingExtractionResultSchema = z.object({
  vendorId: z.string().uuid(),
  runId: z.string().uuid(),
  prices: z.array(
    z.object({
      courseType: courseTypeSchema,
      priceCents: z.number().int().nonnegative(),
      currency: z.string().default("USD"),
      sourceUrl: z.string().url(),
      evidenceSnippet: z.string(),
      confidence: confidenceSchema
    })
  )
});

export const bookingClassificationResultSchema = z.object({
  vendorId: z.string().uuid(),
  runId: z.string().uuid(),
  bookingCapability: bookingCapabilitySchema,
  bookingUrl: z.string().url().optional(),
  providerHint: z.string().optional(),
  sourceUrl: z.string().url(),
  evidenceSnippet: z.string(),
  confidence: confidenceSchema
});

export const enrichmentStatusSchema = z.object({
  vendorId: z.string().uuid(),
  runId: z.string().uuid(),
  stage: enrichmentStageSchema,
  status: stageStatusSchema,
  errorSummary: z.string().optional(),
  startedAt: z.string().datetime().optional(),
  completedAt: z.string().datetime().optional()
});

export const reviewItemSchema = z.object({
  vendorId: z.string().uuid(),
  runId: z.string().uuid().optional(),
  reasonCode: z.string().min(1),
  severity: reviewSeveritySchema.default("medium"),
  status: reviewStatusSchema.default("open"),
  payload: z.record(z.any()).default({})
});

export const vendorFieldEvidenceSchema = z.object({
  vendorId: z.string().uuid(),
  runId: z.string().uuid(),
  fieldKey: z.string(),
  valueText: z.string().optional(),
  valueJson: z.record(z.any()).optional(),
  sourceUrl: z.string().url(),
  sourceType: sourceTypeSchema,
  evidenceSnippet: z.string(),
  confidence: confidenceSchema,
  extractorType: z.enum(["deterministic", "ai"]),
  extractedAt: z.string().datetime()
});
