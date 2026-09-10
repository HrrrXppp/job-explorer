from __future__ import annotations

import json

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


def test_html_omits_matches_at_or_below_20_percent() -> None:
    html = render_html(
        [_row("n-high", 20.1, "New keep"), _row("n-edge", 20.0, "New drop"), _row("n-low", 10.0, "New trash")],
        [_row("p-high", 55.0, "Prev keep"), _row("p-low", 0.0, "Prev drop")],
    )
    assert "New keep" in html
    assert "20.1%" in html
    assert "Prev keep" in html
    assert "New drop" not in html
    assert "New trash" not in html
    assert "Prev drop" not in html
    assert "20.0%" not in html
    assert "10.0%" not in html


def test_message_keeps_low_scores_in_state_attachment() -> None:
    from datetime import datetime, timezone

    message = build_message(
        sender="me@example.com",
        to=["me@example.com"],
        new_rows=[_row("n-high", 80.0, "Shown"), _row("n-low", 12.0, "Hidden")],
        previous_rows=[_row("p-low", 5.0, "Also hidden")],
        fingerprints={"primary": "sha256:x"},
        when=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
    )
    assert message["Subject"].startswith("[job-explorer] 1 new, 0 previous")
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "Shown" in html
    assert "Hidden" not in html
    assert "Also hidden" not in html
    payload = None
    for part in message.iter_attachments():
        if part.get_filename() == STATE_FILENAME:
            body = part.get_content()
            if isinstance(body, bytes):
                body = body.decode()
            payload = json.loads(body)
    assert payload is not None
    ids = {row["id"] for row in payload["positions"]}
    assert ids == {"n-high", "n-low", "p-low"}


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
