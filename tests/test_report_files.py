from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from job_explorer.models import ScoredPosition
from job_explorer.report_files import load_previous_state, list_state_jsons, write_report
from job_explorer.state import encode_state


def _row(pid: str, title: str) -> ScoredPosition:
    return ScoredPosition(
        id=pid,
        title=title,
        url=f"https://example.com/{pid}",
        source_id="example",
        scores={"primary": 50.0},
    )


def test_write_report_uses_utc_date_time_filenames(tmp_path: Path) -> None:
    when = datetime(2026, 9, 15, 13, 4, 5, tzinfo=timezone.utc)
    html_path, json_path = write_report(
        tmp_path,
        html="<html></html>",
        state_json='{"version": 2}',
        when=when,
    )
    assert html_path.name == "job-explorer-2026-09-15T130405Z.html"
    assert json_path.name == "job-explorer-2026-09-15T130405Z.json"
    assert html_path.read_text(encoding="utf-8") == "<html></html>"
    assert json_path.read_text(encoding="utf-8") == '{"version": 2}'


def test_load_previous_state_reads_gmail_attachment_name(tmp_path: Path) -> None:
    payload = encode_state({"primary": "sha256:seed"}, [_row("example:1", "Seed")])
    (tmp_path / "job-explorer-state.json").write_text(payload, encoding="utf-8")
    state = load_previous_state(tmp_path)
    assert state.resume_fingerprints["primary"] == "sha256:seed"
    assert "example:1" in state.position_ids


def test_load_previous_state_merges_newest_seven_json_files(tmp_path: Path) -> None:
    for day in range(1, 9):
        write_report(
            tmp_path,
            html="",
            state_json=encode_state(
                {"primary": f"sha256:day{day}"},
                [_row(f"example:{day}", f"Day {day}")],
            ),
            when=datetime(2026, 1, day, tzinfo=timezone.utc),
        )
    state = load_previous_state(tmp_path)
    assert state.resume_fingerprints["primary"] == "sha256:day8"
    assert state.position_ids == {f"example:{day}" for day in range(2, 9)}
    assert "example:1" not in state.position_ids
    names = [path.name for path in list_state_jsons(tmp_path)]
    assert names[0] == "job-explorer-2026-01-08T000000Z.json"


def test_corrupt_json_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "job-explorer-state.json").write_text("not-json", encoding="utf-8")
    state = load_previous_state(tmp_path)
    assert state.positions == []
    assert state.position_ids == set()
