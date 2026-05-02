import pLimit, { type LimitFunction } from "p-limit";
import { env } from "@/lib/env";

const hostLimiters = new Map<string, LimitFunction>();

function hostname(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "__unknown__";
  }
}

export function getHostLimiter(url: string): LimitFunction {
  const host = hostname(url);
  let limiter = hostLimiters.get(host);
  if (!limiter) {
    limiter = pLimit(env.ENRICHMENT_PER_HOST_CONCURRENCY);
    hostLimiters.set(host, limiter);
  }
  return limiter;
}

export function hostDelay(): Promise<void> {
  const ms = env.ENRICHMENT_REQUEST_DELAY_MS;
  if (ms <= 0) return Promise.resolve();
  const jitter = Math.floor(Math.random() * Math.min(ms, 500));
  return new Promise((resolve) => setTimeout(resolve, ms + jitter));
}
