"""A minimal `HttpSession` test double for collector contract tests — not a test module."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeHttpSession:
    """Returns one canned response regardless of URL — every WP04 collector
    issues exactly one request per `fetch()`, so that's all a collector test
    needs to drive.
    """

    json_response: Any = None
    text_response: str = ""
    raises: Exception | None = None
    calls: list[str] = field(default_factory=list)

    def get_json(self, url: str, *, params: Mapping[str, str] | None = None) -> Any:
        self.calls.append(url)
        if self.raises is not None:
            raise self.raises
        return self.json_response

    def get_text(self, url: str, *, params: Mapping[str, str] | None = None) -> str:
        self.calls.append(url)
        if self.raises is not None:
            raise self.raises
        return self.text_response

    def post_json(self, url: str, *, json: Mapping[str, Any]) -> Any:
        self.calls.append(url)
        if self.raises is not None:
            raise self.raises
        return self.json_response
