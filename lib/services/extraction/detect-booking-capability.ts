import { bookingClassificationResultSchema } from "@/lib/schemas/core";

const directSignals = [/book now/i, /register now/i, /schedule/i, /checkout/i];
const inquirySignals = [/contact us/i, /inquiry/i, /call to book/i];

export function detectBookingCapability(params: {
  vendorId: string;
  runId: string;
  sourceUrl: string;
  text: string;
}) {
  const hasDirect = directSignals.some((pattern) => pattern.test(params.text));
  const hasInquiry = inquirySignals.some((pattern) => pattern.test(params.text));

  const bookingCapability = hasDirect ? "direct_booking" : hasInquiry ? "inquiry_only" : "unclear";
  const confidence = hasDirect ? 0.85 : hasInquiry ? 0.65 : 0.35;

  return bookingClassificationResultSchema.parse({
    vendorId: params.vendorId,
    runId: params.runId,
    bookingCapability,
    sourceUrl: params.sourceUrl,
    evidenceSnippet: hasDirect ? "Direct booking call-to-action found." : "No explicit booking flow found.",
    confidence
  });
}
