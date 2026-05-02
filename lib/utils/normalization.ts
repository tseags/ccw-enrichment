export function normalizeVendorName(name: string): string {
  return name.trim().toLowerCase().replace(/[^\w\s]/g, "").replace(/\s+/g, " ");
}

export function parseEmails(text: string): string[] {
  const matches = text.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi) ?? [];
  return [...new Set(matches.map((v) => v.toLowerCase()))];
}

export function parsePhones(text: string): string[] {
  const matches = text.match(/(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}/g) ?? [];
  return [...new Set(matches.map((v) => v.trim()))];
}
