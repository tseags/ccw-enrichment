export const websiteResolutionPrompt = `
Rank website candidates for a CCW training vendor.
Return strict JSON with:
- selectedUrl
- confidence (0..1)
- reasons[]
`;

export const pricingExtractionPrompt = `
Extract pricing fields for:
- initial_16hr_day1
- initial_16hr_day2
- initial_16hr_full
- renewal_8hr
Return strict JSON array with price_cents, source_url, confidence, evidence_snippet.
`;

export const bookingClassificationPrompt = `
Classify booking capability as:
- direct_booking
- inquiry_only
- none
- unclear
Return strict JSON with confidence and evidence_snippet.
`;
