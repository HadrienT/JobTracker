"""`html_to_text` — descriptions must read as text whatever the source sent."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from jobtracker.normalize.text import html_to_text

# Verbatim from a live Squarepoint posting on Greenhouse: HTML that arrives entity-escaped.
_GREENHOUSE_ESCAPED = (
    "&lt;p&gt;&lt;strong&gt;Please only apply to the one job you feel best fits."
    "&lt;/strong&gt;&lt;/p&gt;\n"
    "&lt;p id=&quot;id-1.JTRJobDescription-RoleOverview&quot;&gt;&lt;strong&gt;Position "
    "Overview:&lt;/strong&gt;&lt;/p&gt;\n"
    "&lt;div class=&quot;x_elementToProof&quot; data-olk-copy-source=&quot;MessageBody&quot;&gt;"
    "Squarepoint is seeking talented&amp;nbsp;graduate‑level candidates&amp;nbsp;who are "
    "eager&lt;/div&gt;\n&lt;div class=&quot;x_elementToProof&quot;&gt;&amp;nbsp;&lt;/div&gt;\n"
    "&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;li&gt;C++ &amp;amp; R&amp;amp;D&lt;/li&gt;&lt;/ul&gt;"
)


def test_escaped_greenhouse_html_becomes_paragraphs_and_bullets() -> None:
    text = html_to_text(_GREENHOUSE_ESCAPED)
    assert text == (
        "Please only apply to the one job you feel best fits.\n\n"
        "Position Overview:\n\n"
        "Squarepoint is seeking talented graduate‑level candidates who are eager\n\n"
        "• Python\n• C++ & R&D"
    )


def test_no_tag_or_entity_survives() -> None:
    text = html_to_text(_GREENHOUSE_ESCAPED)
    for leftover in ("&lt;", "&gt;", "&quot;", "&nbsp;", "&amp;", "<p", "<div", "</"):
        assert leftover not in text


def test_real_html_is_handled_too() -> None:
    assert (
        html_to_text("<p>Hello&nbsp;<b>world</b></p><p>Bye<br>now</p>") == "Hello world\n\nBye\nnow"
    )


def test_script_and_style_content_is_dropped() -> None:
    assert (
        html_to_text("<style>p{color:red}</style><p>Visible</p><script>evil()</script>")
        == "Visible"
    )


@pytest.mark.parametrize(
    "plain",
    [
        "Join our trading team. C++ required.",
        "We use C++ <20 & R&D; a < b",
        "Engineering Lead: Options\n\n\n\nAbout Keyrock",
        "",
    ],
)
def test_plain_text_is_left_untouched(plain: str) -> None:
    assert html_to_text(plain) == plain


@given(st.text())
def test_html_to_text_is_idempotent(raw: str) -> None:
    once = html_to_text(raw)
    assert html_to_text(once) == once


@given(st.text(alphabet=st.characters(blacklist_characters="<>&"), max_size=200))
def test_text_without_markup_characters_is_the_identity(raw: str) -> None:
    assert html_to_text(raw) == raw
