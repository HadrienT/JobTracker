"""A scriptable text/JSON `HttpSession` for aggregator tests — not a test module."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TextSession:
    """Answers `get_text` by URL substring; records every call with its params.

    `routes` are checked in order, first match wins; an unmatched URL is a test
    bug and raises. `""` is what `PolicedHttpSession` returns for a spent budget.
    """

    routes: list[tuple[str, str]]
    calls: list[tuple[str, Mapping[str, str] | None]] = field(default_factory=list)

    def get_text(self, url: str, *, params: Mapping[str, str] | None = None) -> str:
        self.calls.append((url, params))
        for needle, body in self.routes:
            if needle in url:
                return body
        raise AssertionError(f"unexpected request: {url}")

    def get_json(self, url: str, *, params: Mapping[str, str] | None = None) -> Any:
        raise AssertionError("aggregator collectors must go through get_text (challenge check)")

    def post_json(self, url: str, *, json: Mapping[str, Any]) -> Any:
        raise AssertionError("aggregators never POST")
