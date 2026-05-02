"use client";

import { useRef, useState } from "react";

export default function ImportPage() {
  const [county, setCounty] = useState("");
  const [sourceType, setSourceType] = useState<"manual" | "pdf" | "webpage">("manual");
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [importPdfUrl, setImportPdfUrl] = useState("");
  const [importPageUrl, setImportPageUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0] ?? null;
    if (picked && picked.type !== "application/pdf") {
      setResult("Only PDF files are accepted.");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      return;
    }
    setFile(picked);
    setResult("");
    if (picked) setSourceType("pdf");
  }

  function clearFile() {
    setFile(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  function hasSource(): boolean {
    if (file) return true;
    if (importPdfUrl.trim()) return true;
    if (importPageUrl.trim()) return true;
    if (sourceText.trim()) return true;
    return false;
  }

  async function onImport() {
    if (!county.trim()) {
      setResult("County is required (e.g. San Diego, san-diego, or UUID).");
      return;
    }
    if (!hasSource()) {
      setResult("Paste text, upload a PDF, or enter a PDF or web page URL.");
      return;
    }

    setLoading(true);
    setResult("");

    try {
      let res: Response;

      if (file) {
        const form = new FormData();
        form.append("county", county.trim());
        form.append("sourceType", sourceType);
        if (sourceUrl.trim()) form.append("sourceUrl", sourceUrl.trim());
        form.append("file", file);
        res = await fetch("/api/import", { method: "POST", body: form });
      } else {
        res = await fetch("/api/import", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            county: county.trim(),
            sourceType,
            sourceUrl: sourceUrl.trim() || undefined,
            sourceText: sourceText.trim() || undefined,
            importPdfUrl: importPdfUrl.trim() || undefined,
            importPageUrl: importPageUrl.trim() || undefined
          })
        });
      }

      const data = await res.json();
      setResult(res.ok ? `Imported ${data.rows} rows` : data.error);
    } catch {
      setResult("Network error — is the dev server running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Import County Source</h2>
      <p className="text-sm text-slate-600">
        Set the county by name, slug (e.g. san-diego), or UUID. Then paste text, upload a PDF, or give a URL to a PDF or an HTML page (tables are extracted).
      </p>
      <div className="grid gap-3 rounded border bg-white p-4">
        <input
          value={county}
          onChange={(e) => setCounty(e.target.value)}
          className="rounded border px-3 py-2"
          placeholder="County — e.g. San Diego or san-diego or UUID"
        />
        <select
          value={sourceType}
          onChange={(e) => setSourceType(e.target.value as "manual" | "pdf" | "webpage")}
          className="rounded border px-3 py-2"
        >
          <option value="manual">manual</option>
          <option value="pdf">pdf</option>
          <option value="webpage">webpage</option>
        </select>
        <input
          value={sourceUrl}
          onChange={(e) => setSourceUrl(e.target.value)}
          className="rounded border px-3 py-2"
          placeholder="Source URL for your records (optional)"
        />

        <div className="space-y-1">
          <label className="block text-sm font-medium text-slate-700">Import from PDF URL (https)</label>
          <input
            value={importPdfUrl}
            onChange={(e) => setImportPdfUrl(e.target.value)}
            className="w-full rounded border px-3 py-2 text-sm"
            placeholder="https://example.com/list.pdf"
            disabled={Boolean(file)}
          />
        </div>

        <div className="space-y-1">
          <label className="block text-sm font-medium text-slate-700">Import from web page URL (HTML tables)</label>
          <input
            value={importPageUrl}
            onChange={(e) => setImportPageUrl(e.target.value)}
            className="w-full rounded border px-3 py-2 text-sm"
            placeholder="https://example.com/vendors"
            disabled={Boolean(file)}
          />
        </div>

        <div className="space-y-1">
          <label className="block text-sm font-medium text-slate-700">Or upload a PDF file</label>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,application/pdf"
            onChange={handleFileChange}
            className="block w-full text-sm file:mr-3 file:rounded file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm file:font-medium hover:file:bg-slate-200"
          />
          {file && (
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <span>
                {file.name} ({(file.size / 1024).toFixed(0)} KB)
              </span>
              <button type="button" onClick={clearFile} className="text-red-600 hover:underline">
                Remove
              </button>
            </div>
          )}
        </div>

        {!file && (
          <textarea
            value={sourceText}
            onChange={(e) => setSourceText(e.target.value)}
            className="min-h-52 rounded border px-3 py-2"
            placeholder="Or paste text — one vendor per line..."
          />
        )}
        {file && (
          <p className="text-xs text-slate-500">
            Text is extracted from the PDF on the server. Remove the file to use URLs or pasted text instead.
          </p>
        )}

        <button
          onClick={onImport}
          disabled={loading}
          className="w-fit rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {loading ? "Importing…" : "Parse + Import"}
        </button>
        {result && (
          <p className={`text-sm ${result.startsWith("Imported") ? "text-emerald-700" : "text-red-600"}`}>
            {result}
          </p>
        )}
      </div>
    </section>
  );
}
