"""A `curl_cffi`-backed `HttpClient` — for the sources that block non-browser TLS.

blueprint/00-PRIMER.md §5 (forbidden n°9): TLS impersonation comes **before** any
headless browser. It is an `HttpClient` like `httpx.Client`, so `PolicedHttpSession`
keeps applying the one shared policy (jitter, budget, 403/429 → `SourceBlocked`).

Two details keep the impersonation coherent: the honest `User-Agent` the session
sets is dropped (curl sends the impersonated browser's own — a Chrome TLS
fingerprint with a `JobTracker/0.1` UA is the tell), and `Content-Encoding` is
stripped from the reply because curl has already decoded the body.
"""

from collections.abc import Mapping
from typing import Any, cast

import httpx

from jobtracker.core.errors import SourceUnavailable

_DROPPED_REQUEST_HEADERS = frozenset({"user-agent"})
_DROPPED_RESPONSE_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})


class CurlCffiClient:
    def __init__(
        self, *, impersonate: str = "chrome", default_headers: Mapping[str, str] | None = None
    ) -> None:
        self._impersonate = impersonate
        self._default_headers = dict(default_headers or {})

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        try:
            from curl_cffi import requests as curl_requests  # the optional `aggregators` extra
            from curl_cffi.requests import exceptions as curl_exceptions
        except ImportError as exc:
            raise SourceUnavailable(
                "curl_cffi is not installed (uv sync --extra aggregators)"
            ) from exc

        merged = {**self._default_headers, **(headers or {})}
        merged = {k: v for k, v in merged.items() if k.lower() not in _DROPPED_REQUEST_HEADERS}
        try:
            response = curl_requests.request(
                cast(Any, method),
                url,
                params=dict(params) if params else None,
                json=dict(json) if json is not None else None,
                headers=merged,
                timeout=timeout or 20.0,
                impersonate=cast(Any, self._impersonate),
            )
        except curl_exceptions.Timeout as exc:
            raise httpx.ReadTimeout(str(exc)) from exc
        except curl_exceptions.RequestException as exc:
            raise httpx.ConnectError(str(exc)) from exc
        kept = {
            k: v
            for k, v in response.headers.items()
            if v is not None and k.lower() not in _DROPPED_RESPONSE_HEADERS
        }
        return httpx.Response(response.status_code, headers=kept, content=response.content)
