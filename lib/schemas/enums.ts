import { z } from "zod";

export const sourceTypeSchema = z.enum(["pdf", "webpage", "manual"]);
export const runTriggerTypeSchema = z.enum(["manual", "batch", "scheduled"]);
export const runScopeTypeSchema = z.enum(["vendor", "county", "all"]);
export const runStatusSchema = z.enum(["queued", "running", "completed", "failed"]);
export const enrichmentStageSchema = z.enum(["website", "crawl", "pricing", "booking", "finalize"]);
export const stageStatusSchema = z.enum(["queued", "running", "completed", "failed", "skipped"]);
export const extractorTypeSchema = z.enum(["deterministic", "ai"]);
export const bookingCapabilitySchema = z.enum(["direct_booking", "inquiry_only", "none", "unclear"]);
export const reviewStatusSchema = z.enum(["open", "in_review", "resolved", "dismissed"]);
export const reviewSeveritySchema = z.enum(["low", "medium", "high", "critical"]);
export const vendorStatusSchema = z.enum(["new", "ready_for_enrichment", "enriched", "needs_review"]);
export const courseTypeSchema = z.enum([
  "initial_16hr_day1",
  "initial_16hr_day2",
  "initial_16hr_full",
  "renewal_8hr"
]);
