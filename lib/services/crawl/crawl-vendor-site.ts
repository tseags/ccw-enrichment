import * as cheerio from "cheerio";
import pRetry from "p-retry";
import { pageCrawlResultSchema } from "@/lib/schemas/core";
import { getHostLimiter, hostDelay } from "./host-limiter";

async function fetchAndParse(url: string) {
  const response = await fetch(url, {
    redirect: "follow",
    signal: AbortSignal.timeout(30_000)
  });
  const html = await response.text();
  const $ = cheerio.load(html);
  const text = $("body").text().replace(/\s+/g, " ").trim().slice(0, 30_000);
  return { response, pageTitle: $("title").text() || undefined, text };
}

export async function crawlVendorSite(params: {
  vendorId: string;
  runId: string;
  url: string;
  maxRetries?: number;
}) {
  const limiter = getHostLimiter(params.url);
  const maxRetries = params.maxRetries ?? 2;

  const { response, pageTitle, text } = await limiter(async () => {
    await hostDelay();
    return pRetry(() => fetchAndParse(params.url), {
      retries: maxRetries,
      minTimeout: 2_000,
      factor: 2,
      onFailedAttempt(err) {
        if (err.message.includes("AbortSignal")) throw err;
      }
    });
  });

  return pageCrawlResultSchema.parse({
    vendorId: params.vendorId,
    runId: params.runId,
    url: params.url,
    finalUrl: response.url,
    retrievalMethod: "http",
    httpStatus: response.status,
    pageTitle,
    extractedText: text,
    fetchedAt: new Date().toISOString()
  });
}
