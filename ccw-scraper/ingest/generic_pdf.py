"""
Generic PDF ingest for any county with source_type='pdf' in county_registry.COUNTIES.

Shared pipeline: HTTP fetch → pdfplumber text extraction → Claude structured extraction → dedup.
If the PDF has no extractable text (scanned pages), rasterize with PyMuPDF and use Claude vision on each page.

Local PDF override: set {COUNTY_SLUG}_PDF_PATH where COUNTY_SLUG is the slug in
UPPER_SNAKE_CASE.  Examples:
    LOS_ANGELES_PDF_PATH=/tmp/lasd.pdf
    ALPINE_PDF_PATH=~/Downloads/alpine-ccw.pdf
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import pdfplumber
import requests
from anthropic import Anthropic
from dotenv import load_dotenv

from ingest.base import BaseIngest
from ingest.county_registry import COUNTIES

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

BASE_SYSTEM_PROMPT = (
    "Extract CCW (Carry Concealed Weapon) training vendor/instructor information "
    "from the following raw text extracted from a county sheriff's PDF document. "
    "Return ONLY valid JSON: a single JSON array of objects. Each object MUST have "
    "these keys: vendor_name, city, state, instructor_names (array of strings), "
    "email, website_url (add https:// if missing, null if absent), phone. "
    "Use null for any missing field. Parse EVERY distinct business or instructor "
    "entry as its own object — do not merge separate businesses. "
    "Ignore page headers, footers, page numbers, fee schedules, disclaimer text, "
    "and any non-vendor content."
)

# Maximum characters per chunk sent to Claude.  Pages are grouped until this
# threshold so that small PDFs go in one call while large ones are split.
_CHUNK_MAX_CHARS = 6000

# Rasterize at ~150 DPI for vision fallback on scanned PDFs.
_VISION_MATRIX = 150 / 72
_LLM_RETRIES = 5
_LLM_BACKOFF_SECONDS = 2

VISION_SYSTEM_PROMPT = (
    "Extract CCW (Carry Concealed Weapon) training vendor/instructor information "
    "from images of county sheriff CCW vendor list PDF pages. "
    "Return ONLY valid JSON: a single JSON array of objects. Each object MUST have "
    "these keys: vendor_name, city, state, instructor_names (array of strings), "
    "email, website_url (add https:// if missing, null if absent), phone. "
    "Use null for any missing field. Parse EVERY distinct business or instructor "
    "entry as its own object — do not merge separate businesses. "
    "Ignore page headers, footers, page numbers, fee schedules, disclaimer text, "
    "and any non-vendor content."
)


# ---------------------------------------------------------------------------
# Shared utilities (intentionally self-contained; san_diego.py has its own copies)
# ---------------------------------------------------------------------------

def _parse_claude_json(text: str) -> Any:
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip() in ("```", ""):
            if lines[-1].strip() == "```":
                lines = lines[:-1]
                break
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    if not t:
        raise ValueError("empty JSON after stripping assistant markdown")
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        for start_ch in ("[", "{"):
            i = t.find(start_ch)
            if i >= 0:
                try:
                    return json.loads(t[i:])
                except json.JSONDecodeError:
                    continue
        raise


def _coerce_vendor_dicts(parsed: Any) -> list[dict[str, Any]]:
    if isinstance(parsed, list):
        return [x for x in parsed if isinstance(x, dict)]
    if isinstance(parsed, dict):
        nested = parsed.get("vendors")
        if isinstance(nested, list):
            return [x for x in nested if isinstance(x, dict)]
        return [parsed]
    return []


def _normalize_website(url: str | None) -> str | None:
    if url is None:
        return None
    u = str(url).strip()
    if not u:
        return None
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u.lstrip("/")
    p = urlparse(u)
    netloc = p.netloc.lower()
    path = p.path.rstrip("/")
    return urlunparse(("https", netloc, path, p.params, p.query, p.fragment))


def _normalize_dedup_key(name: str | None) -> str:
    if not name:
        return ""
    cleaned = re.sub(r"[^\w\s]", "", name.lower())
    return " ".join(cleaned.split())


def _extract_annot_uri(obj: Any) -> str | None:
    """Best-effort URI extraction from pdfplumber hyperlink/annotation payloads."""
    if isinstance(obj, str):
        s = obj.strip()
        if re.match(r"^https?://", s, re.I):
            return s
        return None
    if not isinstance(obj, dict):
        return None

    direct_keys = ("uri", "url", "URI")
    for k in direct_keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    action = obj.get("A")
    if isinstance(action, dict):
        for k in direct_keys:
            v = action.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

    data = obj.get("data")
    if isinstance(data, dict):
        nested = _extract_annot_uri(data)
        if nested:
            return nested

    return None


# ---------------------------------------------------------------------------
# Generic PDF ingest class
# ---------------------------------------------------------------------------

class GenericPdfIngest(BaseIngest):
    """Works for any county whose registry entry has source_type='pdf'."""

    def __init__(self, county_slug: str) -> None:
        meta = COUNTIES.get(county_slug)
        if not meta:
            raise ValueError(f"County {county_slug!r} not found in COUNTIES registry")
        if meta["source_type"] not in ("pdf", "google_drive_pdf"):
            raise ValueError(
                f"County {county_slug!r} has source_type={meta['source_type']!r}, "
                "expected 'pdf' or 'google_drive_pdf'"
            )

        self.county_slug = county_slug
        self._source_url: str = meta["source_url"]
        self._source_type: str = meta["source_type"]
        self._notes: str = meta.get("notes", "")
        self._name: str = meta["name"]
        self._vendor_count: int | None = meta.get("vendor_count")

        api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is empty or unset. Add your key to ccw-scraper/.env "
                "or export ANTHROPIC_API_KEY in your shell."
            )
        self._client = Anthropic(api_key=api_key)

    @property
    def _env_pdf_path_key(self) -> str:
        """Env var name for manual PDF override, e.g. LOS_ANGELES_PDF_PATH."""
        return self.county_slug.upper().replace("-", "_") + "_PDF_PATH"

    # -- fetch ---------------------------------------------------------------

    def _site_root(self) -> str:
        """Derive the site root from the source URL for session warm-up."""
        p = urlparse(self._source_url)
        return f"{p.scheme}://{p.netloc}/"

    def fetch(self) -> bytes:
        local = os.environ.get(self._env_pdf_path_key)
        if local:
            p = Path(local).expanduser()
            print(f"[{self.county_slug}] Using local PDF: {p}")
            return p.read_bytes()

        print(f"[{self.county_slug}] Downloading PDF from {self._source_url}")

        sess = requests.Session()
        sess.headers.update(FETCH_HEADERS)

        # Some sites (CivicPlus, Drupal, Akamai) set session cookies on the
        # first HTML page load and 403 bare PDF requests without them.
        root = self._site_root()
        try:
            sess.get(root, timeout=30, allow_redirects=True)
        except requests.RequestException:
            pass  # warm-up is best-effort

        resp = sess.get(
            self._source_url,
            timeout=120,
            allow_redirects=True,
        )
        if resp.status_code == 403:
            raise ValueError(
                f"HTTP 403 downloading {self._source_url!r}. The site may block "
                f"automated requests. Download the PDF manually and set "
                f"{self._env_pdf_path_key}=/path/to/file.pdf, then retry."
            )
        resp.raise_for_status()

        ct = (resp.headers.get("content-type") or "").lower()
        if "pdf" not in ct and not resp.content.startswith(b"%PDF"):
            raise ValueError(
                f"Expected PDF from {self._source_url!r}, got content-type={ct!r}. "
                f"Set {self._env_pdf_path_key}=/path/to/file.pdf to use a local copy."
            )
        return resp.content

    # -- parse ---------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        parts = [BASE_SYSTEM_PROMPT]
        if self._notes:
            parts.append(f"\nContext about this county's PDF: {self._notes}")
        return "\n".join(parts)

    def _build_vision_system_prompt(self) -> str:
        parts = [VISION_SYSTEM_PROMPT]
        if self._notes:
            parts.append(f"\nContext about this county's PDF: {self._notes}")
        return "\n".join(parts)

    @staticmethod
    def _raster_pages_png(raw: bytes) -> list[bytes] | None:
        try:
            import fitz
        except ImportError:
            return None
        doc = fitz.open(stream=raw, filetype="pdf")
        pngs: list[bytes] = []
        try:
            mat = fitz.Matrix(_VISION_MATRIX, _VISION_MATRIX)
            for page in doc:
                pix = page.get_pixmap(matrix=mat, alpha=False)
                pngs.append(pix.tobytes("png"))
        finally:
            doc.close()
        return pngs

    def _append_parsed_vendors(
        self,
        parsed: Any,
        chunk: str,
        seen: set[str],
        out: list[dict[str, Any]],
    ) -> None:
        for data in _coerce_vendor_dicts(parsed):
            vendor_name = data.get("vendor_name")
            key = _normalize_dedup_key(vendor_name)
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)

            website = _normalize_website(data.get("website_url"))
            raw_ins = data.get("instructor_names")
            if raw_ins is None:
                instructor_names: list[str] = []
            elif isinstance(raw_ins, str):
                instructor_names = [raw_ins] if raw_ins.strip() else []
            else:
                instructor_names = [str(x) for x in raw_ins]

            out.append({
                "county": self.county_slug,
                "vendor_name": vendor_name,
                "instructor_names": instructor_names,
                "website_url": website,
                "phone": data.get("phone"),
                "email": data.get("email"),
                "city": data.get("city"),
                "state": data.get("state"),
                "source_url": self._source_url,
                "source_type": self._source_type,
                "raw_block": chunk,
            })

    def _parse_via_raster_vision(self, raw: bytes) -> list[dict[str, Any]]:
        pngs = self._raster_pages_png(raw)
        if pngs is None:
            print(
                f"[{self.county_slug}] Install pymupdf for scanned-PDF vision fallback "
                f"(pip install pymupdf)"
            )
            return []
        if not pngs:
            return []

        print(
            f"[{self.county_slug}] No embedded text; using vision on {len(pngs)} "
            f"raster page(s) …"
        )
        system = self._build_vision_system_prompt()
        seen: set[str] = set()
        out: list[dict[str, Any]] = []

        for i, png in enumerate(pngs, 1):
            print(f"[{self.county_slug}] Vision: page {i}/{len(pngs)} ({len(png)} bytes PNG) …")
            b64 = base64.standard_b64encode(png).decode("ascii")
            chunk_tag = f"[vision page {i}/{len(pngs)}]"
            msg = self._client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=8192,
                system=system,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    f"This is page {i} of {len(pngs)} of a CCW vendor "
                                    "list PDF (scanned). Extract every vendor row visible "
                                    "on this page as a JSON array only (no prose)."
                                ),
                            },
                        ],
                    }
                ],
            )
            text = "".join(b.text for b in msg.content if b.type == "text")
            if not text.strip():
                print(f"[{self.county_slug}] WARNING: empty vision response for page {i}")
                continue
            try:
                parsed = _parse_claude_json(text)
            except (json.JSONDecodeError, ValueError) as exc:
                print(
                    f"[{self.county_slug}] WARNING: JSON parse failed for vision page "
                    f"{i}: {exc} — skipping page"
                )
                continue
            self._append_parsed_vendors(parsed, chunk_tag, seen, out)

        print(f"[{self.county_slug}] Vision done — {len(out)} unique vendors extracted")
        if self._vendor_count is not None:
            delta = len(out) - self._vendor_count
            label = "over" if delta > 0 else "under" if delta < 0 else "exact match"
            print(
                f"[{self.county_slug}] Registry expects ~{self._vendor_count} vendors, "
                f"got {len(out)} ({label}, Δ{delta:+d})"
            )
        return out

    @staticmethod
    def _extract_pages(raw: bytes) -> list[str]:
        pages: list[str] = []
        with pdfplumber.open(BytesIO(raw)) as pdf:
            for page in pdf.pages:
                visible_text = page.extract_text() or ""

                raw_links: list[Any] = []
                page_links = getattr(page, "hyperlinks", None)
                if isinstance(page_links, list):
                    raw_links.extend(page_links)

                # Fallback for PDFs where links are only represented as annotations.
                page_annots = getattr(page, "annots", None)
                if isinstance(page_annots, list):
                    raw_links.extend(page_annots)

                normalized_links: list[str] = []
                seen_links: set[str] = set()
                for link_obj in raw_links:
                    extracted = _extract_annot_uri(link_obj)
                    normalized = _normalize_website(extracted)
                    if not normalized or normalized in seen_links:
                        continue
                    seen_links.add(normalized)
                    normalized_links.append(normalized)

                text = visible_text.strip()
                if normalized_links:
                    hyperlinks_line = "Hyperlinks on this page: " + ", ".join(normalized_links)
                    text = (
                        f"{text}\n\n{hyperlinks_line}"
                        if text
                        else hyperlinks_line
                    )

                if text:
                    pages.append(text)
        return pages

    @staticmethod
    def _chunk_pages(pages: list[str], max_chars: int = _CHUNK_MAX_CHARS) -> list[str]:
        """Group consecutive pages into chunks under *max_chars*."""
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for text in pages:
            if current and current_len + len(text) > max_chars:
                chunks.append("\n\n--- page break ---\n\n".join(current))
                current = []
                current_len = 0
            current.append(text)
            current_len += len(text)
        if current:
            chunks.append("\n\n--- page break ---\n\n".join(current))
        return chunks

    def parse(self, raw: bytes) -> list[dict[str, Any]]:
        pages = self._extract_pages(raw)
        if not pages:
            vision_out = self._parse_via_raster_vision(raw)
            if vision_out:
                return vision_out
            print(f"[{self.county_slug}] WARNING: no text extracted from PDF")
            return []

        chunks = self._chunk_pages(pages)
        system = self._build_system_prompt()
        seen: set[str] = set()
        out: list[dict[str, Any]] = []

        print(
            f"[{self.county_slug}] Extracted {len(pages)} page(s), "
            f"grouped into {len(chunks)} chunk(s)"
        )

        for i, chunk in enumerate(chunks, 1):
            print(
                f"[{self.county_slug}] Sending chunk {i}/{len(chunks)} "
                f"({len(chunk)} chars) to Claude …"
            )
            msg = None
            for attempt in range(1, _LLM_RETRIES + 1):
                try:
                    msg = self._client.messages.create(
                        model=CLAUDE_MODEL,
                        max_tokens=8192,
                        system=system,
                        messages=[{"role": "user", "content": chunk}],
                    )
                    break
                except Exception as exc:
                    text = str(exc).lower()
                    is_retryable = (
                        "overloaded" in text
                        or "529" in text
                        or "rate_limit" in text
                        or "timeout" in text
                        or "temporarily unavailable" in text
                    )
                    if not is_retryable or attempt == _LLM_RETRIES:
                        raise
                    sleep_s = _LLM_BACKOFF_SECONDS ** attempt
                    print(
                        f"[{self.county_slug}] Claude call failed on chunk {i} "
                        f"(attempt {attempt}/{_LLM_RETRIES}): {exc}. "
                        f"Retrying in {sleep_s}s …"
                    )
                    time.sleep(sleep_s)

            if msg is None:
                continue
            text = "".join(b.text for b in msg.content if b.type == "text")
            if not text.strip():
                print(f"[{self.county_slug}] WARNING: empty response for chunk {i}")
                continue

            try:
                parsed = _parse_claude_json(text)
            except (json.JSONDecodeError, ValueError) as exc:
                print(
                    f"[{self.county_slug}] WARNING: JSON parse failed for chunk {i}: "
                    f"{exc}  — skipping chunk"
                )
                continue

            self._append_parsed_vendors(parsed, chunk, seen, out)

        print(f"[{self.county_slug}] Done — {len(out)} unique vendors extracted")
        if self._vendor_count is not None:
            delta = len(out) - self._vendor_count
            label = "over" if delta > 0 else "under" if delta < 0 else "exact match"
            print(
                f"[{self.county_slug}] Registry expects ~{self._vendor_count} vendors, "
                f"got {len(out)} ({label}, Δ{delta:+d})"
            )
        return out
