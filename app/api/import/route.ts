import { NextResponse } from "next/server";
import pdfParse from "pdf-parse";
import {
  createCountySource,
  createVendorCountyListing,
  insertCountySourceRows,
  insertVendorContacts,
  resolveCountyId,
  upsertVendor
} from "@/lib/db/repositories";
import { fetchPdfTextFromUrl, fetchWebPageTextFromUrl } from "@/lib/services/ingestion/fetch-import-source";
import { parseCountySource } from "@/lib/services/ingestion/parse-county-source";
import { normalizeVendorRow } from "@/lib/services/normalization/normalize-vendor-row";

const MAX_PDF_BYTES = 10 * 1024 * 1024; // 10 MB

type ImportParams = {
  countyId: string;
  sourceType: "pdf" | "webpage" | "manual";
  sourceText: string;
  sourceUrl?: string;
  notes?: string;
};

function countyInputFromForm(form: FormData): string {
  const county = (form.get("county") as string | null)?.trim();
  const countyId = (form.get("countyId") as string | null)?.trim();
  return county || countyId || "";
}

async function extractParamsFromRequest(req: Request): Promise<ImportParams> {
  const contentType = req.headers.get("content-type") ?? "";

  if (contentType.includes("multipart/form-data")) {
    const form = await req.formData();
    const countyRaw = countyInputFromForm(form);
    const sourceType = ((form.get("sourceType") as string | null) ?? "manual") as ImportParams["sourceType"];
    const sourceUrlMeta = ((form.get("sourceUrl") as string | null) || "").trim() || undefined;
    const notes = ((form.get("notes") as string | null) || "").trim() || undefined;
    const file = form.get("file") as File | null;
    const pastedText = ((form.get("sourceText") as string | null) || "").trim();
    const importPdfUrl = ((form.get("importPdfUrl") as string | null) || "").trim();
    const importPageUrl = ((form.get("importPageUrl") as string | null) || "").trim();

    if (!countyRaw) throw new Error("County is required (name, slug, or UUID)");

    let sourceText = pastedText;
    let sourceUrl = sourceUrlMeta;

    if (file && file.size > 0) {
      if (file.type !== "application/pdf") {
        throw new Error("Only PDF files are accepted");
      }
      if (file.size > MAX_PDF_BYTES) {
        throw new Error(`PDF exceeds ${MAX_PDF_BYTES / 1024 / 1024} MB limit`);
      }
      const buffer = Buffer.from(await file.arrayBuffer());
      const parsed = await pdfParse(buffer);
      if (!parsed.text.trim()) {
        throw new Error("PDF contains no extractable text (scanned image?)");
      }
      sourceText = parsed.text;
    } else if (importPdfUrl) {
      sourceText = await fetchPdfTextFromUrl(importPdfUrl);
      sourceUrl = sourceUrl ?? importPdfUrl;
    } else if (importPageUrl) {
      sourceText = await fetchWebPageTextFromUrl(importPageUrl);
      sourceUrl = sourceUrl ?? importPageUrl;
    }

    if (!sourceText.trim()) {
      throw new Error("Provide pasted text, a PDF upload, a PDF URL, or a web page URL");
    }

    const countyId = await resolveCountyId(countyRaw);

    return {
      countyId,
      sourceType,
      sourceText,
      sourceUrl,
      notes
    };
  }

  const body = (await req.json()) as {
    county?: string;
    countyId?: string;
    sourceType?: ImportParams["sourceType"];
    sourceText?: string;
    sourceUrl?: string;
    notes?: string;
    importPdfUrl?: string;
    importPageUrl?: string;
  };

  const countyRaw = (body.county ?? body.countyId ?? "").trim();
  if (!countyRaw) throw new Error("County is required (name, slug, or UUID)");

  let sourceText = (body.sourceText ?? "").trim();
  let sourceUrl = body.sourceUrl?.trim() || undefined;
  const importPdfUrl = body.importPdfUrl?.trim() ?? "";
  const importPageUrl = body.importPageUrl?.trim() ?? "";

  if (importPdfUrl) {
    sourceText = await fetchPdfTextFromUrl(importPdfUrl);
    sourceUrl = sourceUrl ?? importPdfUrl;
  } else if (importPageUrl) {
    sourceText = await fetchWebPageTextFromUrl(importPageUrl);
    sourceUrl = sourceUrl ?? importPageUrl;
  }

  if (!sourceText.trim()) {
    throw new Error("Provide sourceText, importPdfUrl, or importPageUrl");
  }

  const countyId = await resolveCountyId(countyRaw);

  return {
    countyId,
    sourceType: body.sourceType ?? "manual",
    sourceText,
    sourceUrl,
    notes: body.notes?.trim() || undefined
  };
}

export async function POST(req: Request) {
  try {
    const body = await extractParamsFromRequest(req);

    const source = await createCountySource({
      countyId: body.countyId,
      sourceType: body.sourceType,
      sourceUrl: body.sourceUrl,
      notes: body.notes
    });

    const rows = parseCountySource({
      countyId: body.countyId,
      countySourceId: source.id,
      sourceText: body.sourceText
    });
    const savedRows = await insertCountySourceRows(rows);

    for (const row of rows) {
      const normalized = normalizeVendorRow(row);
      const vendor = await upsertVendor(normalized);
      const sourceRecord = savedRows.find((item) => item.row_index === row.rowIndex);
      await createVendorCountyListing({
        vendorId: vendor.id,
        countyId: body.countyId,
        countySourceId: source.id,
        sourceRecordId: sourceRecord?.id
      });
      await insertVendorContacts({ vendorId: vendor.id, contacts: normalized.contacts });
    }

    return NextResponse.json({ sourceId: source.id, rows: rows.length });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Import failed" },
      { status: 500 }
    );
  }
}
