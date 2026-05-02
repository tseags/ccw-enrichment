"""
Generic webpage ingest for any county with source_type='webpage' in county_registry.COUNTIES.

Shared pipeline: HTTP fetch → BeautifulSoup body text extraction → Claude structured extraction → dedup.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests
from anthropic import Anthropic
from bs4 import BeautifulSoup
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

_CHUNK_MAX_CHARS = 12_000

SYSTEM_PROMPT = (
    "Extract CCW (Carry Concealed Weapon) training vendor/instructor information "
    "from the following text scraped from a county sheriff's webpage. "
    "Return ONLY valid JSON: a single JSON array of objects. Each object MUST have "
    "these keys: vendor_name, city, state, instructor_names (array of strings), "
    "email, website_url (add https:// if missing, null if absent), phone. "
    "Use null for any missing field. Parse EVERY distinct business or instructor "
    "entry as its own object — do not merge separate businesses. "
    "Ignore page navigation, headers, footers, disclaimers, fee schedules, "
    "and any non-vendor content. If instructor names are not listed, return an "
    "empty array for instructor_names."
)


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


def _extract_body_text(html: str) -> str:
    """Strip nav/header/footer/script/style and return cleaned body text."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()

    body = soup.find("body")
    if body is None:
        body = soup

    lines: list[str] = []
    for elem in body.stripped_strings:
        lines.append(elem)
    return "\n".join(lines)


class GenericWebpageIngest(BaseIngest):
    """Works for any county whose registry entry has source_type='webpage'."""

    def __init__(self, county_slug: str) -> None:
        meta = COUNTIES.get(county_slug)
        if not meta:
            raise ValueError(f"County {county_slug!r} not found in COUNTIES registry")
        if meta["source_type"] != "webpage":
            raise ValueError(
                f"County {county_slug!r} has source_type={meta['source_type']!r}, "
                "expected 'webpage'"
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
    def _env_html_path_key(self) -> str:
        """Env var name for manual HTML override, e.g. MENDOCINO_HTML_PATH."""
        return self.county_slug.upper().replace("-", "_") + "_HTML_PATH"

    def _site_root(self) -> str:
        p = urlparse(self._source_url)
        return f"{p.scheme}://{p.netloc}/"

    def fetch(self) -> bytes:
        local = os.environ.get(self._env_html_path_key)
        if not local:
            local_path = Path(__file__).resolve().parent.parent / "data" / "raw" / f"{self.county_slug}.html"
            if local_path.exists():
                local = str(local_path)

        if local:
            p = Path(local).expanduser()
            print(f"[{self.county_slug}] Using local HTML: {p}")
            return p.read_bytes()

        print(f"[{self.county_slug}] Fetching webpage from {self._source_url}")

        sess = requests.Session()
        sess.headers.update(FETCH_HEADERS)

        root = self._site_root()
        try:
            sess.get(root, timeout=30, allow_redirects=True)
        except requests.RequestException:
            pass

        resp = sess.get(self._source_url, timeout=60, allow_redirects=True)
        if resp.status_code == 403:
            raise ValueError(
                f"HTTP 403 fetching {self._source_url!r}. The site blocks automated "
                f"requests. Save the page HTML to data/raw/{self.county_slug}.html "
                f"or set {self._env_html_path_key}=/path/to/file.html, then retry."
            )
        resp.raise_for_status()
        return resp.content

    def _build_system_prompt(self) -> str:
        parts = [SYSTEM_PROMPT]
        if self._notes:
            parts.append(f"\nContext about this county's webpage: {self._notes}")
        return "\n".join(parts)

    @staticmethod
    def _chunk_text(text: str, max_chars: int = _CHUNK_MAX_CHARS) -> list[str]:
        if len(text) <= max_chars:
            return [text]
        lines = text.split("\n")
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in lines:
            if current and current_len + len(line) + 1 > max_chars:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            current.append(line)
            current_len += len(line) + 1
        if current:
            chunks.append("\n".join(current))
        return chunks

    def parse(self, raw: bytes) -> list[dict[str, Any]]:
        html = raw.decode("utf-8", errors="replace")
        body_text = _extract_body_text(html)

        if not body_text.strip():
            print(f"[{self.county_slug}] WARNING: no text extracted from webpage")
            return []

        chunks = self._chunk_text(body_text)
        system = self._build_system_prompt()
        seen: set[str] = set()
        out: list[dict[str, Any]] = []

        print(
            f"[{self.county_slug}] Extracted {len(body_text)} chars of body text, "
            f"grouped into {len(chunks)} chunk(s)"
        )

        for i, chunk in enumerate(chunks, 1):
            print(
                f"[{self.county_slug}] Sending chunk {i}/{len(chunks)} "
                f"({len(chunk)} chars) to Claude …"
            )
            msg = self._client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=8192,
                system=system,
                messages=[{"role": "user", "content": chunk}],
            )
            text = "".join(b.text for b in msg.content if b.type == "text")
            if not text.strip():
                print(f"[{self.county_slug}] WARNING: empty response for chunk {i}")
                continue

            try:
                parsed = _parse_claude_json(text)
            except (json.JSONDecodeError, ValueError) as exc:
                print(
                    f"[{self.county_slug}] WARNING: JSON parse failed for chunk {i}: "
                    f"{exc} — skipping chunk"
                )
                continue

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

        print(f"[{self.county_slug}] Done — {len(out)} unique vendors extracted")
        if self._vendor_count is not None:
            delta = len(out) - self._vendor_count
            label = "over" if delta > 0 else "under" if delta < 0 else "exact match"
            print(
                f"[{self.county_slug}] Registry expects ~{self._vendor_count} vendors, "
                f"got {len(out)} ({label}, Δ{delta:+d})"
            )
        return out
