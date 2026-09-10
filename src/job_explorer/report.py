from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.message import EmailMessage

from bs4 import BeautifulSoup

from job_explorer.models import ScoredPosition
from job_explorer.state import STATE_FILENAME, encode_state

SUBJECT_PREFIX = "[job-explorer]"
EMAIL_MIN_PERCENT = 20.0
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def email_visible_rows(rows: list[ScoredPosition]) -> list[ScoredPosition]:
    return [row for row in rows if row.best_percent > EMAIL_MIN_PERCENT]


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(value).replace("\xa0", " ")
    if _HTML_TAG.search(text):
        text = BeautifulSoup(text, "lxml").get_text(" ", strip=True)
    return " ".join(text.split())


def snippet(text: str | None, limit: int = 160) -> str:
    compact = html_to_text(text)
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def render_html(
    new_rows: list[ScoredPosition],
    previous_rows: list[ScoredPosition],
) -> str:
    parts = [
        "<html><body>",
        "<h1>Job explorer report</h1>",
        _section("New positions", email_visible_rows(new_rows)),
        _section("Previous positions", email_visible_rows(previous_rows)),
        "</body></html>",
    ]
    return "\n".join(parts)


def _section(title: str, rows: list[ScoredPosition]) -> str:
    lines = [f"<h2>{html.escape(title)}</h2>"]
    if not rows:
        lines.append("<p>None</p>")
        return "\n".join(lines)
    lines.append("<ol>")
    for row in rows:
        title_html = html.escape(row.title or row.id)
        if row.url:
            safe_url = html.escape(row.url, quote=True)
            title_html = f'<a href="{safe_url}">{title_html}</a>'
        extra_scores = ""
        if len(row.scores) > 1:
            extras = ", ".join(
                f"{html.escape(rid)} {pct:.1f}%"
                for rid, pct in sorted(row.scores.items(), key=lambda item: item[1], reverse=True)
                if rid != row.best_resume_id
            )
            if extras:
                extra_scores = f" <small>also {extras}</small>"
        snippet_html = ""
        if row.snippet:
            snippet_html = f"<br><small>{html.escape(row.snippet)}</small>"
        lines.append(
            "<li>"
            f"<strong>{row.best_percent:.1f}%</strong> {title_html} "
            f"— {html.escape(row.source_id)} / {html.escape(row.best_resume_id)}"
            f"{extra_scores}{snippet_html}"
            "</li>"
        )
    lines.append("</ol>")
    return "\n".join(lines)


def subject_line(n_new: int, n_prev: int, when: datetime | None = None) -> str:
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%MZ")
    return f"{SUBJECT_PREFIX} {n_new} new, {n_prev} previous · {stamp}"


def build_message(
    *,
    sender: str,
    to: list[str],
    new_rows: list[ScoredPosition],
    previous_rows: list[ScoredPosition],
    fingerprints: dict[str, str],
    when: datetime | None = None,
) -> EmailMessage:
    html_body = render_html(new_rows, previous_rows)
    state_json = encode_state(fingerprints, new_rows + previous_rows)
    visible_new = email_visible_rows(new_rows)
    visible_previous = email_visible_rows(previous_rows)
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(to)
    message["Subject"] = subject_line(len(visible_new), len(visible_previous), when)
    message.set_content("HTML report attached; open in an HTML-capable client.")
    message.add_alternative(html_body, subtype="html")
    message.add_attachment(
        state_json.encode("utf-8"),
        maintype="application",
        subtype="json",
        filename=STATE_FILENAME,
    )
    return message
