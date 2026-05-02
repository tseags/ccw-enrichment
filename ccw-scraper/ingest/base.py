from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseIngest(ABC):
    """County ingest: fetch source, parse into vendor records."""

    county_slug: str

    @abstractmethod
    def fetch(self) -> bytes:
        """Download raw source (e.g. PDF bytes)."""

    @abstractmethod
    def parse(self, raw: bytes) -> list[dict[str, Any]]:
        """Turn raw bytes into structured vendor dicts."""

    def run(self) -> list[dict[str, Any]]:
        raw = self.fetch()
        return self.parse(raw)
