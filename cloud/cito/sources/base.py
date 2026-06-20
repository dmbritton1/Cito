"""The pluggability contract: every content source is a fetcher + a prompt fragment."""

from typing import Protocol


class Source(Protocol):
    name: str

    def fetch(self) -> dict:
        """Return normalized, meaning-shaped structured data (not raw API shape)."""
        ...

    def prompt_fragment(self, data: dict) -> str:
        """Return a source-specific instruction + the data for the engine prompt."""
        ...
