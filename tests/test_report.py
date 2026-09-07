from __future__ import annotations

from job_explorer.models import ScoredPosition
from job_explorer.report import build_message, render_html, snippet
from job_explorer.state import STATE_FILENAME


def _row(pid: str, percent: float, title: str | None = None) -> ScoredPosition:
    return ScoredPosition(
        id=pid,
        title=title or pid,
        url=f"https://example.com/{pid}",
        source_id="example",
        scores={"primary": percent},
        snippet="snippet text" if percent > 50 else None,
    )


def test_html_has_both_headings_and_order() -> None:
    html = render_html(
        [_row("n1", 90.0, "New high"), _row("n2", 40.0, "New low")],
        [_row("p1", 70.0, "Prev")],
    )
    assert "<h2>New positions</h2>" in html
    assert "<h2>Previous positions</h2>" in html
    assert html.index("New high") < html.index("New low")
    assert "90.0%" in html
    assert 'href="https://example.com/n1"' in html
    assert "None" not in html


def test_empty_sections_say_none() -> None:
    html = render_html([], [])
    assert html.count("None") == 2


def test_message_attachment_name_and_subject() -> None:
    from datetime import datetime, timezone

    message = build_message(
        sender="me@example.com",
        to=["me@example.com"],
        new_rows=[_row("n", 80.0)],
        previous_rows=[],
        fingerprints={"primary": "sha256:x"},
        when=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
    )
    assert message["Subject"].startswith("[job-explorer] 1 new, 0 previous")
    filenames = [
        part.get_filename()
        for part in message.iter_attachments()
    ]
    assert STATE_FILENAME in filenames


def test_snippet_truncates() -> None:
    text = "word " * 80
    assert snippet(text).endswith("…")
    assert snippet(None) == ""
    assert snippet("short") == "short"


def test_snippet_strips_html_and_entities() -> None:
    raw = '<p style="margin: 0px 0px 16px; scrollbar-width: thin;">&nbsp;We have an opportunity to impact your career</p>'
    assert snippet(raw) == "We have an opportunity to impact your career"
    assert "<p" not in snippet(raw)
    assert "&nbsp;" not in snippet(raw)
