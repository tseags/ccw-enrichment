import { cleanEnv, num, str, url } from "envalid";

export const env = cleanEnv(process.env, {
  NODE_ENV: str({ default: "development" }),
  NEXT_PUBLIC_SUPABASE_URL: url(),
  NEXT_PUBLIC_SUPABASE_ANON_KEY: str(),
  SUPABASE_SERVICE_ROLE_KEY: str(),
  OPENAI_API_KEY: str({ default: "" }),
  GOOGLE_CLIENT_EMAIL: str({ default: "" }),
  GOOGLE_PRIVATE_KEY: str({ default: "" }),
  GOOGLE_SHEETS_ID: str({ default: "" }),
  /** Comma-separated domain suffixes allowed for PDF/web URL import (e.g. ca.gov,sandiegocounty.gov). Empty = any public https host after DNS safety checks. */
  IMPORT_FETCH_ALLOWED_HOSTS: str({ default: "" }),

  /** Worker: max vendor enrichments running at once. */
  ENRICHMENT_GLOBAL_CONCURRENCY: num({ default: 3 }),
  /** Worker: max concurrent HTTP requests to the same hostname. */
  ENRICHMENT_PER_HOST_CONCURRENCY: num({ default: 1 }),
  /** Worker: milliseconds to wait between requests to the same host. */
  ENRICHMENT_REQUEST_DELAY_MS: num({ default: 1500 }),
  /** Worker: seconds between queue polls when idle. */
  ENRICHMENT_POLL_INTERVAL_S: num({ default: 5 }),
  /** Worker: max retries per vendor on transient errors. */
  ENRICHMENT_MAX_RETRIES: num({ default: 2 })
});
