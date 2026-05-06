/**
 * Full replace of carry_class_vendor_data from ccw-scraper CSV master.
 *
 * Usage (from repo root):
 *   npm run db:load-enriched
 *   npm run db:load-enriched -- --csv=ccw-scraper/data/enriched/all-vendors.with-google-placeids.csv
 *   ENRICHED_CSV_PATH=ccw-scraper/data/enriched/foo.csv npm run db:load-enriched
 *
 * Path precedence: --csv / --csv=… overrides ENRICHED_CSV_PATH; default is all-vendors.csv.
 * Relative paths resolve from process.cwd() (repo root).
 *
 * Requires .env.local with Supabase service role (same as other scripts).
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import Papa from "papaparse";
import { getSupabaseAdminClient } from "@/lib/db/supabase";

const DEFAULT_CSV_RELATIVE = path.join("ccw-scraper", "data", "enriched", "all-vendors.csv");
const CHUNK = 250;

function resolvedCsvPath(): string {
  const argv = process.argv.slice(2);
  let fromCli: string | undefined;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--csv=")) {
      fromCli = a.slice("--csv=".length);
      break;
    }
    if (a === "--csv" && argv[i + 1]) {
      fromCli = argv[++i];
      break;
    }
  }
  const explicit = fromCli?.trim() || process.env.ENRICHED_CSV_PATH?.trim();
  if (!explicit) {
    return path.join(process.cwd(), DEFAULT_CSV_RELATIVE);
  }
  return path.isAbsolute(explicit) ? explicit : path.join(process.cwd(), explicit);
}

type CsvRow = Record<string, string>;

function toRow(r: CsvRow) {
  return {
    county: (r.county ?? "").trim(),
    needs_review: (r.needs_review ?? "").trim() || null,
    vendor_name: (r.vendor_name ?? "").trim(),
    instructor_names: (r.instructor_names ?? "").trim() || null,
    email: (r.email ?? "").trim() || null,
    phone: (r.phone ?? "").trim() || null,
    website_url: (r.website_url ?? "").trim() || null,
    booking_capability: (r.booking_capability ?? "").trim() || null,
    city: (r.city ?? "").trim() || null,
    state: (r.state ?? "").trim() || null,
    address: (r.address ?? "").trim() || null,
    price_16hr_full: (r.price_16hr_full ?? "").trim() || null,
    price_8hr_renewal: (r.price_8hr_renewal ?? "").trim() || null,
    price_add_a_gun: (r.price_add_a_gun ?? "").trim() || null,
    vendor_description: (r.vendor_description ?? "").trim() || null,
    crawl_status: (r.crawl_status ?? "").trim() || null,
    enrichment_confidence: (r.enrichment_confidence ?? "").trim() || null,
    confidence_notes: (r.confidence_notes ?? "").trim() || null,
    logo_path: (r.logo_path ?? "").trim() || null,
    instructor_image_paths: (r.instructor_image_paths ?? "").trim() || null,
    training_image_paths: (r.training_image_paths ?? "").trim() || null,
    enriched_at: (r.enriched_at ?? "").trim() || null,
    google_place_id: (r.google_place_id ?? "").trim() || null,
    google_reviews_url: (r.google_reviews_url ?? "").trim() || null
  };
}

async function main() {
  const csvPath = resolvedCsvPath();
  console.log(`Loading CSV: ${csvPath}`);
  const raw = readFileSync(csvPath, "utf8");
  const parsed = Papa.parse<CsvRow>(raw, { header: true, skipEmptyLines: true });
  if (parsed.errors.length) {
    console.error(parsed.errors);
    process.exit(1);
  }

  const rows = (parsed.data as CsvRow[])
    .map(toRow)
    .filter((r) => r.county && r.vendor_name);

  const supabase = getSupabaseAdminClient();

  const { error: delErr } = await supabase.from("carry_class_vendor_data").delete().not("id", "is", null);
  if (delErr) {
    console.error("Delete failed (did you apply migrations through 0006?)", delErr);
    process.exit(1);
  }

  for (let i = 0; i < rows.length; i += CHUNK) {
    const chunk = rows.slice(i, i + CHUNK);
    const { error: insErr } = await supabase.from("carry_class_vendor_data").insert(chunk);
    if (insErr) {
      console.error(`Insert failed at offset ${i}`, insErr);
      process.exit(1);
    }
    console.log(`Inserted ${Math.min(i + CHUNK, rows.length)} / ${rows.length}`);
  }

  console.log(`Done. ${rows.length} rows loaded from ${csvPath}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
