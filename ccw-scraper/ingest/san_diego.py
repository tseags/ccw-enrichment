from __future__ import annotations

import json
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any

import pdfplumber
import requests
from anthropic import Anthropic
from dotenv import load_dotenv

from ingest.base import BaseIngest
from ingest.county_registry import COUNTIES

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

CCW_VENDORS_PAGE = (
    "https://www.sdsheriff.gov/i-want-to/get-a-permit-or-license/"
    "regulatory-licenses-and-fees/ccw-vendors"
)

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

FETCH_PDF_HEADERS = {
    **{k: v for k, v in FETCH_HEADERS.items() if k != "Accept"},
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Referer": CCW_VENDORS_PAGE,
}

SYSTEM_PROMPT = (
    "Extract CCW vendor info from this raw PDF text block. The PDF uses a "
    "multi-column layout: one line may contain SEVERAL distinct vendor business "
    "names side-by-side, with contact details mixed below—parse EVERY separate "
    "company/training business as its own record. Return ONLY valid JSON: a "
    "single JSON array of objects (use one-element array if there is only one "
    "vendor). Each object has: vendor_name, city, state, instructor_names "
    "(array of strings), email, website_url (add https:// if missing, null if "
    "absent), phone. Use null for any missing fields. Do not merge separate "
    "businesses into one record."
)

FOOTER_MARKERS = (
    "SAN DIEGO COUNTY",
    "APPROVED FIREARMS",
    "UPDATED",
    "8-HOUR",
    "16-HOUR",
    "RENEWAL",
    "ONLINE COURSES",
)


def _word_count(line: str) -> int:
    return len(line.split())


def _upper_ratio(line: str) -> float:
    letters = [c for c in line if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def is_vendor_header_line(line: str) -> bool:
    s = line.strip()
    if not s or _word_count(s) < 3:
        return False
    return _upper_ratio(s) >= 0.80


def is_footer_line(line: str) -> bool:
    u = line.upper()
    if any(m in u for m in FOOTER_MARKERS):
        return True
    # Word "Page" (e.g. Page 1 of 6) — avoid naive "PAGE" substring (matches "webpage")
    if re.search(r"\bpage\b", line, re.I):
        return True
    return False


def split_vendor_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    current: list[str] = []

    for raw in lines:
        line = raw.strip()
        if not line:
            if current:
                current.append("")
            continue
        if is_footer_line(line):
            continue
        if is_vendor_header_line(line):
            if current:
                joined = "\n".join(current).strip()
                if joined:
                    blocks.append(joined)
            current = [line]
        elif current:
            current.append(line)

    if current:
        joined = "\n".join(current).strip()
        if joined:
            blocks.append(joined)
    return blocks


def normalize_website(url: str | None) -> str | None:
    if url is None:
        return None
    u = str(url).strip()
    if not u:
        return None
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u.lstrip("/")
    from urllib.parse import urlparse, urlunparse

    p = urlparse(u)
    netloc = p.netloc.lower()
    path = p.path.rstrip("/")
    rebuilt = urlunparse(("https", netloc, path, p.params, p.query, p.fragment))
    return rebuilt


def normalize_vendor_dedup_key(name: str | None) -> str:
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
        # Model sometimes adds a short preamble before the JSON payload.
        for start_ch in ("[", "{"):
            i = t.find(start_ch)
            if i >= 0:
                try:
                    return json.loads(t[i:])
                except json.JSONDecodeError:
                    continue
        raise


def _coerce_vendor_dicts(parsed: Any) -> list[dict[str, Any]]:
    """Model may return one object or an array; sometimes wraps a list under 'vendors'."""
    if isinstance(parsed, list):
        return [x for x in parsed if isinstance(x, dict)]
    if isinstance(parsed, dict):
        nested = parsed.get("vendors")
        if isinstance(nested, list):
            return [x for x in nested if isinstance(x, dict)]
        return [parsed]
    return []


def _extract_page_text_with_hyperlinks(page: Any) -> str:
    visible_text = (page.extract_text() or "").strip()

    raw_links: list[Any] = []
    page_links = getattr(page, "hyperlinks", None)
    if isinstance(page_links, list):
        raw_links.extend(page_links)

    page_annots = getattr(page, "annots", None)
    if isinstance(page_annots, list):
        raw_links.extend(page_annots)

    links: list[str] = []
    seen: set[str] = set()
    for link_obj in raw_links:
        extracted = _extract_annot_uri(link_obj)
        normalized = normalize_website(extracted)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)

    if links:
        hyperlink_line = "Hyperlinks on this page: " + ", ".join(links)
        if visible_text:
            return f"{visible_text}\n\n{hyperlink_line}"
        return hyperlink_line

    return visible_text


class SanDiegoIngest(BaseIngest):
    county_slug = "san-diego"

    def __init__(self) -> None:
        meta = COUNTIES[self.county_slug]
        self._source_url = meta["source_url"]
        self._source_type = meta["source_type"]
        api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is empty or unset. Add your key to ccw-scraper/.env "
                "(save the file on disk) or export ANTHROPIC_API_KEY in your shell."
            )
        self._client = Anthropic(api_key=api_key)

    def fetch(self) -> bytes:
        local = os.environ.get("SAN_DIEGO_PDF_PATH")
        if local:
            return Path(local).expanduser().read_bytes()
        try:
            # Akamai often 403s bare PDF GETs; warm session with the CCW page first.
            sess = requests.Session()
            sess.headers.update(FETCH_HEADERS)
            sess.get(CCW_VENDORS_PAGE, timeout=120)
            r = sess.get(self._source_url, timeout=120, headers=FETCH_PDF_HEADERS)
            r.raise_for_status()
        except requests.HTTPError as e:
            resp = e.response
            if resp is not None and resp.status_code == 403:
                raise RuntimeError(
                    "HTTP 403 when downloading the San Diego PDF. The site may block "
                    "automated requests. Download the PDF from the CCW Vendors page and "
                    "set SAN_DIEGO_PDF_PATH to the local file path, then retry."
                ) from e
            raise
        ct = (r.headers.get("content-type") or "").lower()
        if "pdf" not in ct and not r.content.startswith(b"%PDF"):
            raise ValueError(
                f"Expected PDF from {self._source_url!r}, got content-type={ct!r} "
                f"(len={len(r.content)}). Set SAN_DIEGO_PDF_PATH to a local file if the "
                "site blocks automated downloads."
            )
        return r.content

    def parse(self, raw: bytes) -> list[dict[str, Any]]:
        full_text_parts: list[str] = []
        with pdfplumber.open(BytesIO(raw)) as pdf:
            for page in pdf.pages:
                t = _extract_page_text_with_hyperlinks(page)
                if t:
                    full_text_parts.append(t)
        full_text = "\n".join(full_text_parts)
        blocks = split_vendor_blocks(full_text)
        seen: set[str] = set()
        out: list[dict[str, Any]] = []

        for block in blocks:
            msg = self._client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": block}],
            )
            text = ""
            for b in msg.content:
                if b.type == "text":
                    text += b.text
            if not text.strip():
                raise RuntimeError(
                    "Claude returned no text for a vendor block. "
                    f"Block starts with: {block[:200]!r}"
                )
            parsed = _parse_claude_json(text)
            for data in _coerce_vendor_dicts(parsed):
                vendor_name = data.get("vendor_name")
                key = normalize_vendor_dedup_key(vendor_name)
                if not key:
                    continue
                if key in seen:
                    continue
                seen.add(key)

                website = normalize_website(data.get("website_url"))

                raw_ins = data.get("instructor_names")
                if raw_ins is None:
                    instructor_names: list[str] = []
                elif isinstance(raw_ins, str):
                    instructor_names = [raw_ins] if raw_ins.strip() else []
                else:
                    instructor_names = [str(x) for x in raw_ins]

                rec = {
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
                    "raw_block": block,
                }
                out.append(rec)
        return out
