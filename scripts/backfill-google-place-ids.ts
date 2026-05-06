/**
 * Backfill Google Place IDs into the canonical vendor CSV (or Supabase source rows).
 *
 * Usage examples:
 *   npx tsx --env-file=.env.local scripts/backfill-google-place-ids.ts --dry-run
 *   npx tsx --env-file=.env.local scripts/backfill-google-place-ids.ts --apply
 *   npx tsx --env-file=.env.local scripts/backfill-google-place-ids.ts --apply --in-place
 */
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import path from "node:path";
import Papa from "papaparse";

type SourceMode = "csv" | "supabase";
type Confidence = "high" | "medium" | "low" | "none";

type CliConfig = {
  source: SourceMode;
  input: string;
  output: string;
  reviewOutput: string;
  checkpoint: string;
  cache: string;
  dryRun: boolean;
  apply: boolean;
  inPlace: boolean;
  overwriteExisting: boolean;
  applyConfidence: Set<Confidence>;
  qps: number;
  batchSize: number;
  maxRetries: number;
  resume: boolean;
  applySupabase: boolean;
  supabaseTable: string;
};

type VendorRecord = Record<string, string>;

type Candidate = {
  placeId: string;
  name: string;
  formattedAddress: string;
  phone: string;
  website: string;
  source: "find_place" | "text_search";
};

type MatchResult = {
  googlePlaceId: string;
  googleReviewsUrl: string;
  matchConfidence: Confidence;
  matchReason: string;
  rawCandidatePlaceIds: string[];
  errorMessage: string;
};

type CachedLookup = {
  at: string;
  result: MatchResult;
};

type CheckpointState = {
  processed: Record<string, MatchResult>;
};

const DEFAULT_INPUT = path.join(process.cwd(), "ccw-scraper", "data", "enriched", "all-vendors.csv");
const DEFAULT_OUTPUT = path.join(process.cwd(), "ccw-scraper", "data", "enriched", "all-vendors.with-google-placeids.csv");
const DEFAULT_REVIEW = path.join(process.cwd(), "tmp", "google-placeid-review-needed.csv");
const DEFAULT_CHECKPOINT = path.join(process.cwd(), "tmp", "google-placeid-checkpoint.json");
const DEFAULT_CACHE = path.join(process.cwd(), "tmp", "google-placeid-cache.json");

const OUTPUT_COLUMNS = [
  "google_place_id",
  "google_reviews_url",
  "match_confidence",
  "match_reason",
  "raw_candidate_place_ids",
  "error_message"
];

const GOOGLE_FIND_PLACE_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json";
const GOOGLE_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json";
const GOOGLE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function parseBoolFlag(raw: unknown, defaultValue: boolean): boolean {
  if (raw === undefined) return defaultValue;
  if (typeof raw === "boolean") return raw;
  const s = String(raw).toLowerCase();
  if (["false", "0", "no", "off"].includes(s)) return false;
  if (["true", "1", "yes", "on"].includes(s)) return true;
  return Boolean(raw);
}

function parseArgs(argv: string[]): CliConfig {
  const raw: Record<string, string | boolean> = {};
  for (const arg of argv) {
    if (!arg.startsWith("--")) continue;
    const [k, v] = arg.slice(2).split("=");
    if (v === undefined) raw[k] = true;
    else raw[k] = v;
  }

  const source = (raw.source as SourceMode) ?? "csv";
  if (source !== "csv" && source !== "supabase") {
    throw new Error(`Invalid --source: ${String(raw.source)}`);
  }

  const applyConfidenceRaw = String(raw["apply-confidence"] ?? "high")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean) as Confidence[];

  const applyConfidence = new Set<Confidence>(applyConfidenceRaw);
  for (const c of applyConfidence) {
    if (!["high", "medium", "low", "none"].includes(c)) {
      throw new Error(`Invalid value in --apply-confidence: ${c}`);
    }
  }

  return {
    source,
    input: String(raw.input ?? DEFAULT_INPUT),
    output: String(raw.output ?? DEFAULT_OUTPUT),
    reviewOutput: String(raw["review-output"] ?? DEFAULT_REVIEW),
    checkpoint: String(raw.checkpoint ?? DEFAULT_CHECKPOINT),
    cache: String(raw.cache ?? DEFAULT_CACHE),
    dryRun: parseBoolFlag(raw["dry-run"], false),
    apply: parseBoolFlag(raw.apply, false),
    inPlace: parseBoolFlag(raw["in-place"], false),
    overwriteExisting: parseBoolFlag(raw["overwrite-existing"], false),
    applyConfidence,
    qps: Math.max(0.2, Number(raw.qps ?? 1.5)),
    batchSize: Math.max(1, Number(raw["batch-size"] ?? 200)),
    maxRetries: Math.max(0, Number(raw["max-retries"] ?? 3)),
    resume: parseBoolFlag(raw.resume, true),
    applySupabase: parseBoolFlag(raw["apply-supabase"], false),
    supabaseTable: String(raw["supabase-table"] ?? "carry_class_vendor_data")
  };
}

function normalizeText(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^\w\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizePhone(value: string): string {
  const digits = value.replace(/\D/g, "");
  return digits.length === 11 && digits.startsWith("1") ? digits.slice(1) : digits;
}

function domainFromUrl(value: string): string {
  if (!value) return "";
  try {
    const u = new URL(value.startsWith("http") ? value : `https://${value}`);
    const host = u.hostname.toLowerCase();
    return host.startsWith("www.") ? host.slice(4) : host;
  } catch {
    return "";
  }
}

function getStableId(row: VendorRecord): string {
  const explicitId = row.id?.trim() || row.uuid?.trim() || row.slug?.trim();
  if (explicitId) return explicitId;
  const parts = [row.county, row.vendor_name, row.city, row.state].map((v) => normalizeText(v ?? ""));
  return parts.join("|");
}

function ensureParentDir(filePath: string) {
  const dir = path.dirname(filePath);
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
}

function readJsonFile<T>(filePath: string, fallback: T): T {
  if (!existsSync(filePath)) return fallback;
  try {
    return JSON.parse(readFileSync(filePath, "utf8")) as T;
  } catch {
    return fallback;
  }
}

function writeJsonFile(filePath: string, value: unknown) {
  ensureParentDir(filePath);
  writeFileSync(filePath, JSON.stringify(value, null, 2), "utf8");
}

function buildQuery(row: VendorRecord): string {
  const parts = [row.vendor_name, row.address, row.city, row.state].map((v) => (v ?? "").trim()).filter(Boolean);
  return parts.join(", ");
}

function buildFingerprint(row: VendorRecord): string {
  return [
    normalizeText(row.vendor_name ?? ""),
    normalizeText(row.address ?? ""),
    normalizeText(row.city ?? ""),
    normalizeText(row.state ?? ""),
    normalizePhone(row.phone ?? ""),
    domainFromUrl(row.website_url ?? "")
  ].join("|");
}

function reviewsUrl(placeId: string): string {
  return placeId ? `https://search.google.com/local/reviews?placeid=${encodeURIComponent(placeId)}` : "";
}

function tokenSet(value: string): Set<string> {
  const clean = normalizeText(value);
  return new Set(clean.split(" ").filter(Boolean));
}

function overlapScore(a: string, b: string): number {
  const sa = tokenSet(a);
  const sb = tokenSet(b);
  if (!sa.size || !sb.size) return 0;
  let common = 0;
  for (const t of sa) if (sb.has(t)) common += 1;
  return common / Math.max(sa.size, sb.size);
}

function classifyConfidence(score: number): Confidence {
  if (score >= 80) return "high";
  if (score >= 58) return "medium";
  if (score >= 35) return "low";
  return "none";
}

function scoreCandidate(row: VendorRecord, candidate: Candidate): { score: number; reason: string } {
  let score = 0;
  const reasons: string[] = [];

  const rowPhone = normalizePhone(row.phone ?? "");
  const candPhone = normalizePhone(candidate.phone ?? "");
  if (rowPhone && candPhone) {
    if (rowPhone === candPhone) {
      score += 45;
      reasons.push("exact_phone_match");
    } else {
      score -= 15;
      reasons.push("phone_conflict");
    }
  }

  const rowDomain = domainFromUrl(row.website_url ?? "");
  const candDomain = domainFromUrl(candidate.website ?? "");
  if (rowDomain && candDomain) {
    if (rowDomain === candDomain) {
      score += 25;
      reasons.push("website_domain_match");
    } else {
      score -= 8;
      reasons.push("website_domain_conflict");
    }
  }

  const nameScore = overlapScore(row.vendor_name ?? "", candidate.name);
  if (nameScore >= 0.85) {
    score += 25;
    reasons.push("strong_name_similarity");
  } else if (nameScore >= 0.6) {
    score += 16;
    reasons.push("moderate_name_similarity");
  } else if (nameScore > 0) {
    score += 6;
    reasons.push("weak_name_overlap");
  } else {
    score -= 15;
    reasons.push("name_mismatch");
  }

  const city = normalizeText(row.city ?? "");
  const state = normalizeText(row.state ?? "");
  const addr = normalizeText(row.address ?? "");
  const candAddr = normalizeText(candidate.formattedAddress);

  if (city) {
    if (candAddr.includes(city)) {
      score += 10;
      reasons.push("city_match");
    } else {
      score -= 7;
      reasons.push("city_mismatch");
    }
  }
  if (state) {
    if (candAddr.includes(state)) {
      score += 6;
      reasons.push("state_match");
    } else {
      score -= 5;
      reasons.push("state_mismatch");
    }
  }
  if (addr) {
    const addrScore = overlapScore(addr, candAddr);
    if (addrScore >= 0.6) {
      score += 12;
      reasons.push("address_proximity_strong");
    } else if (addrScore >= 0.35) {
      score += 6;
      reasons.push("address_proximity_partial");
    }
  }

  return { score, reason: reasons.join("|") };
}

async function fetchWithRetry(url: string, maxRetries: number): Promise<Response> {
  let attempt = 0;
  while (true) {
    attempt += 1;
    try {
      const response = await fetch(url);
      if (response.status === 429 && attempt <= maxRetries + 1) {
        const waitMs = Math.min(20000, 400 * 2 ** attempt + Math.floor(Math.random() * 350));
        await sleep(waitMs);
        continue;
      }
      return response;
    } catch (err) {
      if (attempt > maxRetries + 1) throw err;
      const waitMs = Math.min(20000, 450 * 2 ** attempt + Math.floor(Math.random() * 500));
      await sleep(waitMs);
    }
  }
}

function classifyApiStatus(status: string): string {
  if (status === "ZERO_RESULTS") return "ZERO_RESULTS";
  if (status === "REQUEST_DENIED") return "REQUEST_DENIED";
  if (status === "OVER_QUERY_LIMIT") return "OVER_QUERY_LIMIT";
  return status;
}

async function getPlaceDetails(placeId: string, apiKey: string, maxRetries: number, minIntervalMs: number): Promise<{
  phone: string;
  website: string;
}> {
  const params = new URLSearchParams({
    key: apiKey,
    place_id: placeId,
    fields: "formatted_phone_number,website"
  });
  const res = await fetchWithRetry(`${GOOGLE_DETAILS_URL}?${params.toString()}`, maxRetries);
  await sleep(minIntervalMs);
  const json = (await res.json()) as { status?: string; result?: { formatted_phone_number?: string; website?: string } };
  if (!res.ok || (json.status && !["OK", "ZERO_RESULTS"].includes(json.status))) {
    return { phone: "", website: "" };
  }
  return {
    phone: json.result?.formatted_phone_number ?? "",
    website: json.result?.website ?? ""
  };
}

async function resolvePlace(
  row: VendorRecord,
  apiKey: string,
  cache: Record<string, CachedLookup>,
  cfg: CliConfig
): Promise<MatchResult> {
  const minIntervalMs = Math.ceil(1000 / cfg.qps);
  const fingerprint = buildFingerprint(row);
  const cached = cache[fingerprint];
  if (cached) return cached.result;

  const query = buildQuery(row);
  if (!query) {
    const result: MatchResult = {
      googlePlaceId: "",
      googleReviewsUrl: "",
      matchConfidence: "none",
      matchReason: "missing_query_fields",
      rawCandidatePlaceIds: [],
      errorMessage: "Missing vendor_name/city/state data for lookup"
    };
    cache[fingerprint] = { at: new Date().toISOString(), result };
    return result;
  }

  const candidates: Candidate[] = [];

  const findParams = new URLSearchParams({
    key: apiKey,
    input: query,
    inputtype: "textquery",
    fields: "place_id,name,formatted_address"
  });
  const findRes = await fetchWithRetry(`${GOOGLE_FIND_PLACE_URL}?${findParams.toString()}`, cfg.maxRetries);
  await sleep(minIntervalMs);
  const findJson = (await findRes.json()) as {
    status?: string;
    candidates?: Array<{ place_id?: string; name?: string; formatted_address?: string }>;
  };

  if (!findRes.ok) {
    return {
      googlePlaceId: "",
      googleReviewsUrl: "",
      matchConfidence: "none",
      matchReason: "find_place_http_error",
      rawCandidatePlaceIds: [],
      errorMessage: `find_place_http_${findRes.status}`
    };
  }
  if (findJson.status && !["OK", "ZERO_RESULTS"].includes(findJson.status)) {
    return {
      googlePlaceId: "",
      googleReviewsUrl: "",
      matchConfidence: "none",
      matchReason: "find_place_api_error",
      rawCandidatePlaceIds: [],
      errorMessage: classifyApiStatus(findJson.status)
    };
  }

  for (const c of findJson.candidates ?? []) {
    if (!c.place_id) continue;
    candidates.push({
      placeId: c.place_id,
      name: c.name ?? "",
      formattedAddress: c.formatted_address ?? "",
      phone: "",
      website: "",
      source: "find_place"
    });
  }

  if (candidates.length === 0) {
    const textParams = new URLSearchParams({ key: apiKey, query });
    const textRes = await fetchWithRetry(`${GOOGLE_TEXT_SEARCH_URL}?${textParams.toString()}`, cfg.maxRetries);
    await sleep(minIntervalMs);
    const textJson = (await textRes.json()) as {
      status?: string;
      results?: Array<{ place_id?: string; name?: string; formatted_address?: string }>;
    };

    if (!textRes.ok) {
      return {
        googlePlaceId: "",
        googleReviewsUrl: "",
        matchConfidence: "none",
        matchReason: "text_search_http_error",
        rawCandidatePlaceIds: [],
        errorMessage: `text_search_http_${textRes.status}`
      };
    }
    if (textJson.status && !["OK", "ZERO_RESULTS"].includes(textJson.status)) {
      return {
        googlePlaceId: "",
        googleReviewsUrl: "",
        matchConfidence: "none",
        matchReason: "text_search_api_error",
        rawCandidatePlaceIds: [],
        errorMessage: classifyApiStatus(textJson.status)
      };
    }

    for (const r of textJson.results ?? []) {
      if (!r.place_id) continue;
      candidates.push({
        placeId: r.place_id,
        name: r.name ?? "",
        formattedAddress: r.formatted_address ?? "",
        phone: "",
        website: "",
        source: "text_search"
      });
    }
  }

  if (candidates.length === 0) {
    const result: MatchResult = {
      googlePlaceId: "",
      googleReviewsUrl: "",
      matchConfidence: "none",
      matchReason: "no_candidates",
      rawCandidatePlaceIds: [],
      errorMessage: "ZERO_RESULTS"
    };
    cache[fingerprint] = { at: new Date().toISOString(), result };
    return result;
  }

  const uniqueCandidates = Array.from(new Map(candidates.map((c) => [c.placeId, c])).values()).slice(0, 5);
  for (const c of uniqueCandidates.slice(0, 3)) {
    const details = await getPlaceDetails(c.placeId, apiKey, cfg.maxRetries, minIntervalMs);
    c.phone = details.phone;
    c.website = details.website;
  }

  const scored = uniqueCandidates.map((c) => ({ candidate: c, ...scoreCandidate(row, c) })).sort((a, b) => b.score - a.score);
  const top = scored[0];
  const second = scored[1];
  const margin = second ? top.score - second.score : 999;
  let confidence = classifyConfidence(top.score);
  if (confidence === "high" && margin < 10) confidence = "medium";

  const result: MatchResult = {
    googlePlaceId: top.candidate.placeId,
    googleReviewsUrl: reviewsUrl(top.candidate.placeId),
    matchConfidence: confidence,
    matchReason: `${top.reason}|score=${top.score}|margin=${margin}|source=${top.candidate.source}`,
    rawCandidatePlaceIds: uniqueCandidates.map((c) => c.placeId),
    errorMessage: ""
  };
  cache[fingerprint] = { at: new Date().toISOString(), result };
  return result;
}

function assembleOutputRow(row: VendorRecord, match: MatchResult, cfg: CliConfig, allowWrites: boolean): VendorRecord {
  const eligible = candidateEligibleForApply(row, match, cfg);
  const applyGoogle = allowWrites && eligible;

  const existingPid = (row.google_place_id ?? "").trim();
  const existingUrl = (row.google_reviews_url ?? "").trim();

  return {
    ...row,
    google_place_id: applyGoogle ? match.googlePlaceId : existingPid,
    google_reviews_url: applyGoogle ? match.googleReviewsUrl : existingUrl,
    match_confidence: match.matchConfidence,
    match_reason: match.matchReason,
    raw_candidate_place_ids: match.rawCandidatePlaceIds.join(","),
    error_message: match.errorMessage
  };
}

function parseCsv(filePath: string): { rows: VendorRecord[]; headers: string[] } {
  const raw = readFileSync(filePath, "utf8");
  const parsed = Papa.parse<VendorRecord>(raw, { header: true, skipEmptyLines: true });
  if (parsed.errors.length) {
    throw new Error(`CSV parse error in ${filePath}: ${parsed.errors[0].message}`);
  }
  const base = parsed.meta.fields ?? [];
  const extras = OUTPUT_COLUMNS.filter((c) => !base.includes(c));
  const headers = [...base, ...extras];
  return { rows: parsed.data as VendorRecord[], headers };
}

function writeCsv(filePath: string, rows: VendorRecord[], headers: string[]) {
  ensureParentDir(filePath);
  const csv = Papa.unparse(rows, { columns: headers });
  writeFileSync(filePath, csv, "utf8");
}

async function readSupabaseRows(table: string): Promise<VendorRecord[]> {
  const { getSupabaseAdminClient } = await import("@/lib/db/supabase");
  const supabase = getSupabaseAdminClient();
  const { data, error } = await supabase
    .from(table)
    .select("id,county,vendor_name,city,state,address,phone,website_url,google_place_id,google_reviews_url")
    .order("vendor_name", { ascending: true });
  if (error) throw new Error(`Supabase read failed: ${error.message}`);
  return (data ?? []).map((r) => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v == null ? "" : String(v)])));
}

async function updateSupabaseRows(table: string, rows: VendorRecord[], batchSize: number) {
  const { getSupabaseAdminClient } = await import("@/lib/db/supabase");
  const supabase = getSupabaseAdminClient();
  const updates = rows
    .filter((r) => r.id && r.google_place_id)
    .map((r) => ({
      id: r.id,
      google_place_id: r.google_place_id || null,
      google_reviews_url: r.google_reviews_url || null
    }));
  let done = 0;
  for (let i = 0; i < updates.length; i += batchSize) {
    const chunk = updates.slice(i, i + batchSize);
    for (const item of chunk) {
      const { error } = await supabase
        .from(table)
        .update({
          google_place_id: item.google_place_id,
          google_reviews_url: item.google_reviews_url
        })
        .eq("id", item.id);
      if (error) throw new Error(`Supabase update failed for id=${item.id}: ${error.message}`);
      done += 1;
    }
    console.log(`[supabase] updated ${done} / ${updates.length}`);
  }
}

function candidateEligibleForApply(row: VendorRecord, result: MatchResult, cfg: CliConfig): boolean {
  const hasExisting = Boolean((row.google_place_id ?? "").trim());
  if (hasExisting && !cfg.overwriteExisting) return false;
  return cfg.applyConfidence.has(result.matchConfidence) && Boolean(result.googlePlaceId);
}

async function main() {
  const cfg = parseArgs(process.argv.slice(2));
  const apiKey = process.env.GOOGLE_PLACES_API_KEY ?? "";
  if (!apiKey) throw new Error("Missing GOOGLE_PLACES_API_KEY in environment.");
  const dryRunEffective = cfg.dryRun || !cfg.apply;
  if (cfg.dryRun && cfg.apply) {
    console.warn("[warn] Both --dry-run and --apply were passed; dry-run disables all writes.");
  }
  if (cfg.inPlace && dryRunEffective) {
    throw new Error("--in-place requires --apply without --dry-run.");
  }
  if (cfg.applySupabase && dryRunEffective) {
    throw new Error("--apply-supabase requires --apply without --dry-run.");
  }

  const allowWrites = cfg.apply && !dryRunEffective;

  const checkpoint: CheckpointState =
    allowWrites && cfg.resume ? readJsonFile(cfg.checkpoint, { processed: {} }) : { processed: {} };
  const cache: Record<string, CachedLookup> =
    allowWrites && cfg.resume ? readJsonFile(cfg.cache, {}) : {};

  let sourceRows: VendorRecord[];
  let headers: string[];
  if (cfg.source === "csv") {
    const csv = parseCsv(cfg.input);
    sourceRows = csv.rows;
    headers = csv.headers;
  } else {
    sourceRows = await readSupabaseRows(cfg.supabaseTable);
    const keys = sourceRows.length ? Object.keys(sourceRows[0]) : [];
    const extras = OUTPUT_COLUMNS.filter((c) => !keys.includes(c));
    headers = [...keys, ...extras];
  }

  let processed = 0;
  let updated = 0;
  let skippedExisting = 0;
  const confidenceCount: Record<Confidence, number> = { high: 0, medium: 0, low: 0, none: 0 };
  const failures: Record<string, number> = {};

  const outRows: VendorRecord[] = [];
  const reviewRows: VendorRecord[] = [];

  for (const row of sourceRows) {
    processed += 1;
    const stableId = getStableId(row);
    const checkpointed = checkpoint.processed[stableId];
    const result = checkpointed ?? (await resolvePlace(row, apiKey, cache, cfg));
    checkpoint.processed[stableId] = result;

    confidenceCount[result.matchConfidence] += 1;
    if (result.errorMessage) failures[result.errorMessage] = (failures[result.errorMessage] ?? 0) + 1;

    const eligible = candidateEligibleForApply(row, result, cfg);
    const applyGoogle = allowWrites && eligible;
    if (
      allowWrites &&
      (row.google_place_id ?? "").trim() &&
      !cfg.overwriteExisting &&
      cfg.applyConfidence.has(result.matchConfidence) &&
      Boolean(result.googlePlaceId)
    ) {
      skippedExisting += 1;
    }
    if (applyGoogle) updated += 1;

    const merged = assembleOutputRow(row, result, cfg, allowWrites);
    if (result.matchConfidence !== "high") reviewRows.push(merged);
    outRows.push(merged);

    if (processed % 25 === 0) {
      console.log(`[progress] ${processed}/${sourceRows.length} processed`);
      if (allowWrites) {
        writeJsonFile(cfg.checkpoint, checkpoint);
        writeJsonFile(cfg.cache, cache);
      }
    }
  }

  if (allowWrites) {
    writeJsonFile(cfg.checkpoint, checkpoint);
    writeJsonFile(cfg.cache, cache);
  }

  if (allowWrites) {
    if (cfg.source === "csv") {
      if (cfg.inPlace) {
        const stamp = new Date().toISOString().replace(/[:.]/g, "-");
        const backup = cfg.input.replace(/\.csv$/i, `.backup-before-placeid-${stamp}.csv`);
        renameSync(cfg.input, backup);
        writeCsv(cfg.input, outRows, headers);
        console.log(`[write] In-place update complete: ${cfg.input}`);
        console.log(`[write] Backup created: ${backup}`);
      } else {
        writeCsv(cfg.output, outRows, headers);
        console.log(`[write] Output CSV: ${cfg.output}`);
      }
    } else {
      writeCsv(cfg.output, outRows, headers);
      console.log(`[write] Source=supabase output CSV: ${cfg.output}`);
    }

    writeCsv(cfg.reviewOutput, reviewRows, headers);
    console.log(`[write] Review CSV: ${cfg.reviewOutput}`);
  } else {
    console.log("[dry-run] Skipped writing CSV outputs, checkpoint, cache, and Supabase updates.");
  }

  if (cfg.applySupabase && allowWrites) {
    await updateSupabaseRows(cfg.supabaseTable, outRows, cfg.batchSize);
    console.log("[supabase] Direct updates complete.");
  }

  console.log("\nSummary");
  console.log(`- processed: ${processed}`);
  console.log(`- updated: ${updated}`);
  console.log(`- skipped_existing: ${skippedExisting}`);
  console.log(`- high: ${confidenceCount.high}`);
  console.log(`- medium: ${confidenceCount.medium}`);
  console.log(`- low: ${confidenceCount.low}`);
  console.log(`- none: ${confidenceCount.none}`);
  if (Object.keys(failures).length) {
    console.log("- failures:");
    for (const [k, v] of Object.entries(failures)) console.log(`  - ${k}: ${v}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
