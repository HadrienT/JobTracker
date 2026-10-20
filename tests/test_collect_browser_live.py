"""`BrowserClient` against a real Chromium — `live`, since CI installs no browser.

Needs `just browser-install` once, then `uv run pytest -m live` on this file.
"""

import pytest

from jobtracker.collect.browser import BrowserClient

pytestmark = pytest.mark.live


def test_the_body_is_the_dom_after_scripts_ran() -> None:
    page = (
        "data:text/html,<body><script>"
        "document.body.innerHTML='<a href=\"/jobs/1\">Rendered Quant Dev</a>'"
        "</script></body>"
    )
    with BrowserClient() as client:
        response = client.request("GET", page, headers={"User-Agent": "JobTracker-Test/0.1"})
    assert response.status_code == 200
    assert "Rendered Quant Dev" in response.text
