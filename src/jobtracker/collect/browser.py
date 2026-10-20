"""A headless-browser `HttpClient` — for career pages that only exist once rendered.

Most of the registry sits on an ATS with a JSON endpoint and never needs this. The
residue — boards a company hosts itself, or an ATS whose listing is assembled
client-side — serves an empty shell to a plain HTTP client. `BrowserClient` has the
same shape as `httpx.Client` as far as `PolicedHttpSession` is concerned, so the
shared policy (jitter, budget, 403/429 → `SourceBlocked`) applies unchanged: the
"response body" is simply the DOM after the page's scripts have run, iframes included.

A portal's own JSON endpoint is the exception: a caller that asks for JSON (`Accept:
application/json`, what `get_json`/`post_json` send) gets the endpoint's answer as it
is, requested from the same browser context — same cookies, same user agent — with no
page rendered around it.

The session's `User-Agent` is not used here: the page is requested by the browser that
renders it, under that browser's own name.

Playwright is an optional dependency (`uv sync --extra browser`, then `just
browser-install` for Chromium itself) and is imported on first use only, so a
deployment that collects nothing with `source: custom` never needs it.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self

import httpx

_NAVIGATION_TIMEOUT_MS = 45_000
_SETTLE_TIMEOUT_MS = 5_000
_RESETTLE_TIMEOUT_MS = 1_500
_SCROLL_PASSES = 3
_SCROLL_PAUSE_MS = 500
_JSON = "application/json"
# The full browser in its headless mode, not the stripped `headless shell` Playwright
# launches by default: bot walls (Akamai on group.bnpparibas, for one) answer the shell
# with a 403 and the browser with the page.
_CHANNEL = "chromium"
_LAUNCH_ARGS = ("--disable-blink-features=AutomationControlled",)
_UNAVAILABLE = (
    "headless browser unavailable — `uv sync --extra browser`, then `just browser-install`"
)


class BrowserClient:
    """Renders a URL in headless Chromium and hands back the resulting DOM."""

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._api_context: Any = None
        self._user_agent: str | None = None

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
        request = httpx.Request(method, url, params=params)
        wants_json = (headers or {}).get("Accept") == _JSON
        if method != "GET" and not wants_json:
            raise httpx.UnsupportedProtocol(f"BrowserClient only renders GET, not {method}")
        try:
            from playwright.sync_api import Error as PlaywrightError
        except ImportError as exc:
            raise httpx.ConnectError(_UNAVAILABLE, request=request) from exc

        try:
            browser = self._launched()
        except PlaywrightError as exc:
            raise httpx.ConnectError(f"{_UNAVAILABLE} ({exc})", request=request) from exc
        if wants_json:
            return self._call_api(browser, request, json)
        context = browser.new_context(user_agent=self._user_agent, locale="en-US")
        try:
            page = context.new_page()
            response = page.goto(
                str(request.url), wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS
            )
            _settle(page)
            # Lazy-loaded listings only fill in once scrolled into view.
            for _ in range(_SCROLL_PASSES):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(_SCROLL_PAUSE_MS)
            _settle(page, _RESETTLE_TIMEOUT_MS)
            parts = [page.content()]
            for frame in page.frames:
                if frame is not page.main_frame:
                    parts.append(_frame_content(frame))
            status = response.status if response is not None else 200
        except PlaywrightError as exc:
            if "Timeout" in type(exc).__name__:
                raise httpx.ReadTimeout(
                    f"browser timeout rendering {url}", request=request
                ) from exc
            raise httpx.ConnectError(
                f"browser failed rendering {url}: {exc}", request=request
            ) from exc
        finally:
            context.close()
        return httpx.Response(status, text="\n".join(parts), request=request)

    def _call_api(
        self,
        browser: Any,
        request: httpx.Request,
        json: Mapping[str, Any] | None,
    ) -> httpx.Response:
        from playwright.sync_api import Error as PlaywrightError

        if self._api_context is None:
            self._api_context = browser.new_context(user_agent=self._user_agent, locale="en-US")
        try:
            response = self._api_context.request.fetch(
                str(request.url),
                method=request.method,
                headers={"Accept": _JSON},
                data=dict(json) if json is not None else None,
                timeout=_NAVIGATION_TIMEOUT_MS,
            )
            status, body = response.status, response.text()
        except PlaywrightError as exc:
            if "Timeout" in type(exc).__name__ or "Timeout" in str(exc):
                raise httpx.ReadTimeout(
                    f"browser timeout calling {request.url}", request=request
                ) from exc
            raise httpx.ConnectError(
                f"browser failed calling {request.url}: {exc}", request=request
            ) from exc
        return httpx.Response(status, text=body, request=request)

    def close(self) -> None:
        if self._api_context is not None:
            self._api_context.close()
            self._api_context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _launched(self) -> Any:
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=True, channel=_CHANNEL, args=list(_LAUNCH_ARGS)
            )
            # The browser names itself, not the session: a career page is read as the
            # visitor's browser it is rendered in. Headless Chromium announces itself as
            # `HeadlessChrome`, which the same bot walls turn away on sight.
            probe = self._browser.new_page()
            native = str(probe.evaluate("navigator.userAgent"))
            probe.close()
            self._user_agent = native.replace("HeadlessChrome/", "Chrome/")
        return self._browser


def _settle(page: Any, timeout_ms: int = _SETTLE_TIMEOUT_MS) -> None:
    from playwright.sync_api import Error as PlaywrightError

    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightError:
        # A page that keeps polling never goes idle; what it has rendered by now is the answer.
        return


def _frame_content(frame: Any) -> str:
    from playwright.sync_api import Error as PlaywrightError

    try:
        return str(frame.content())
    except PlaywrightError:
        return ""  # a frame that navigated away mid-read has nothing to add
