import { normalizedVendorSchema } from "@/lib/schemas/core";
import type { RawCountyVendorRow } from "@/lib/types";
import { normalizeVendorName } from "@/lib/utils/normalization";

export function normalizeVendorRow(row: RawCountyVendorRow) {
  const name = row.parsedName ?? row.rawText;
  return normalizedVendorSchema.parse({
    canonicalName: name,
    normalizedName: normalizeVendorName(name),
    websiteUrl: row.parsedWebsite,
    hqCity: row.parsedCity,
    contacts: [
      {
        email: row.parsedEmails[0],
        phone: row.parsedPhones[0],
        isPrimary: true
      }
    ].filter((c) => c.email || c.phone)
  });
}
