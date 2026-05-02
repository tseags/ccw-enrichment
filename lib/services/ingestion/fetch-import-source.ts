import { lookup } from "node:dns/promises";
import { load } from "cheerio";
import pdfParse from "pdf-parse";
import { env } from "@/lib/env";

const MAX_BYTES = 10 * 1024 * 1024; // 10 MB — must stay aligned with PDF upload limit

function isPrivateIpv4(ip: string): boolean {
  const p = ip.split(".").map(Number);
  if (p.length !== 4 || p.some((n) => Number.isNaN(n))) return true;
  const [a, b] = p;
  if (a === 10) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  if (a === 192 && b === 168) return true;
  if (a === 127) return true;
  if (a === 169 && b === 254) return true;
  if (a === 0) return true;
  if (a === 100 && b >= 64 && b <= 127) return true; // CGNAT
  return false;
}

function isPrivateIpv6(ip: string): boolean {
  const lower = ip.toLowerCase();
  if (lower === "::1") return true;
  if (lower.startsWith("fe80:")) return true;
  if (lower.startsWith("fc") || lower.startsWith("fd")) return true; // ULA
  if (lower.startsWith("::ffff:")) {
    const v4 = lower.slice(7);
    return isPrivateIpv4(v4);
  }
  return false;
}

async function assertUrlSafeForFetch(urlStr: string): Promise<URL> {
  let url: URL;
  try {
    url = new URL(urlStr);
  } catch {
    throw new Error("Invalid URL");
  }
  if (url.protocol !== "https:") {
    throw new Error("Only https:// URLs are allowed for remote import");
  }
  const host = url.hostname.toLowerCase();
  if (!host || host === "localhost" || host === "0.0.0.0") {
    throw new Error("Host not allowed");
  }
  if (host.endsWith(".local") || host.endsWith(".internal") || host.endsWith(".localhost")) {
    throw new Error("Host not allowed");
  }

  const allow = env.IMPORT_FETCH_ALLOWED_HOSTS.trim();
  if (allow) {
    const rules = allow
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);
    const ok = rules.some((rule) => host === rule || host.endsWith("." + rule));
    if (!ok) {
      throw new Error(
        "Host is not in IMPORT_FETCH_ALLOWED_HOSTS — add it to .env.local (comma-separated domains)"
      );
    }
  }

  let results: { address: string; family: number }[];
  try {
    results = await lookup(host, { all: true, verbatim: true });
  } catch {
    throw new Error("Could not resolve host");
  }
  if (!results.length) throw new Error("Could not resolve host");

  for (const r of results) {
    if (r.family === 4 && isPrivateIpv4(r.address)) {
      throw new Error("Host resolves to a private network address");
    }
    if (r.family === 6 && isPrivateIpv6(r.address)) {
      throw new Error("Host resolves to a private network address");
    }
  }

  return url;
}

async function fetchWithSizeLimit(url: URL): Promise<Buffer> {
  const res = await fetch(url, {
    redirect: "follow",
    headers: { "User-Agent": "ccw-enrichment-import/1.0" }
  });
  if (!res.ok) {
    throw new Error(`Fetch failed (${res.status})`);
  }
  const len = res.headers.get("content-length");
  if (len && parseInt(len, 10) > MAX_BYTES) {
    throw new Error("Remote resource exceeds size limit");
  }
  const reader = res.body?.getReader();
  if (!reader) throw new Error("Empty response body");
  const chunks: Buffer[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    total += value.length;
    if (total > MAX_BYTES) {
      throw new Error("Remote resource exceeds size limit");
    }
    chunks.push(Buffer.from(value));
  }
  return Buffer.concat(chunks);
}

export async function fetchPdfTextFromUrl(urlStr: string): Promise<string> {
  const url = await assertUrlSafeForFetch(urlStr);
  const buffer = await fetchWithSizeLimit(url);
  if (buffer.length < 4 || buffer.subarray(0, 4).toString("ascii") !== "%PDF") {
    throw new Error("URL did not return a PDF (missing %PDF header)");
  }
  const parsed = await pdfParse(buffer);
  if (!parsed.text.trim()) {
    throw new Error("PDF contains no extractable text (scanned image?)");
  }
  return parsed.text;
}

function htmlTablesToText(html: string): string {
  const $ = load(html);
  $("script, style, noscript, svg").remove();
  const lines: string[] = [];
  $("table").each((_, table) => {
    $(table)
      .find("tr")
      .each((__, tr) => {
        const cells = $(tr)
          .find("td, th")
          .map((i, el) =>
            $(el)
              .text()
              .replace(/\s+/g, " ")
              .trim()
          )
          .get()
          .filter(Boolean);
        if (cells.length) lines.push(cells.join(" | "));
      });
  });
  if (lines.length) return lines.join("\n");
  const body = $("body").text().replace(/\s*\n\s*/g, "\n").replace(/[ \t]+/g, " ").trim();
  return body;
}

export async function fetchWebPageTextFromUrl(urlStr: string): Promise<string> {
  const url = await assertUrlSafeForFetch(urlStr);
  const buffer = await fetchWithSizeLimit(url);
  const html = buffer.toString("utf8");
  const text = htmlTablesToText(html);
  if (!text.trim()) {
    throw new Error("No text could be extracted from the page");
  }
  return text;
}
