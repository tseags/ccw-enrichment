import { rawCountyVendorRowSchema } from "@/lib/schemas/core";
import { parseEmails, parsePhones } from "@/lib/utils/normalization";

type ParseInput = {
  countyId: string;
  countySourceId: string;
  sourceText: string;
};

export function parseCountySource(input: ParseInput) {
  const lines = input.sourceText
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  return lines.map((line, idx) =>
    rawCountyVendorRowSchema.parse({
      countyId: input.countyId,
      countySourceId: input.countySourceId,
      rowIndex: idx,
      rawText: line,
      parsedName: line.split(" - ")[0]?.trim() ?? line,
      parsedEmails: parseEmails(line),
      parsedPhones: parsePhones(line),
      parseConfidence: 0.65
    })
  );
}
