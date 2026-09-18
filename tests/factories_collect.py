"""A minimal `HttpSession` test double for collector contract tests — not a test module."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeHttpSession:
    """A scriptable stand-in for `HttpSession`.

    Two modes, picked per instance:
    - `json_response`: every `get_json`/`post_json` call returns the same
      canned value — enough for a collector that issues exactly one request.
    - `responses`: an ordered queue, one entry per call across *both*
      `get_json` and `post_json` (in the order the collector actually makes
      them) — needed for pagination and list-then-detail sequences, where
      each call must see a different response.

    `raise_on` maps a zero-based call index to an exception raised instead of
    returning a response for that one call (e.g. a 404 on the third request).
    """

    json_response: Any = None
    text_response: str = ""
    raises: Exception | None = None
    responses: list[Any] | None = None
    raise_on: dict[int, Exception] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    _call_index: int = field(default=0, init=False, repr=False)

    def _next(self, url: str) -> Any:
        self.calls.append(url)
        index = self._call_index
        self._call_index += 1
        if index in self.raise_on:
            raise self.raise_on[index]
        if self.raises is not None:
            raise self.raises
        if self.responses is not None:
            return self.responses[index]
        return self.json_response

    def get_json(self, url: str, *, params: Mapping[str, str] | None = None) -> Any:
        return self._next(url)

    def get_text(self, url: str, *, params: Mapping[str, str] | None = None) -> str:
        self.calls.append(url)
        if self.raises is not None:
            raise self.raises
        return self.text_response

    def post_json(self, url: str, *, json: Mapping[str, Any]) -> Any:
        return self._next(url)
