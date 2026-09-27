from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
import respx

from job_explorer.cli import run_explorer
from job_explorer.config import load_config
from job_explorer.models import ScoredPosition
from job_explorer.state import encode_state
from tests.conftest import nosleep, write_docx
from tests.test_matching import FakeEncoder


SEARCH = {
    "results": [
        {"id": "old", "title": "Old job", "html_url": "https://example.com/jobs/old"},
        {"id": "new", "title": "New job", "html_url": "https://example.com/jobs/new"},
    ]
}


def _reports(config) -> Path:
    return Path(config.config_dir) / config.reports_dir


@respx.mock
async def test_first_run_all_new_and_sends_user_agent(tmpdir, write_cli_config) -> None:
    resume = write_docx(tmpdir.join("r.docx"), "Python")
    config = load_config(write_cli_config(resume), env={})
    search = respx.get("https://example.com/search").mock(return_value=httpx.Response(200, json=SEARCH))
    respx.get("https://example.com/jobs/old").mock(
        return_value=httpx.Response(200, json={"description": "legacy"})
    )
    respx.get("https://example.com/jobs/new").mock(
        return_value=httpx.Response(200, json={"description": "fresh python"})
    )
    encoder = FakeEncoder({"Python": [1.0, 0.0], "legacy": [0.0, 1.0], "fresh python": [1.0, 0.0]})
    when = datetime(2026, 9, 15, 1, 36, 0, tzinfo=timezone.utc)
    async with httpx.AsyncClient(headers={"User-Agent": config.user_agent}) as client:
        new_rows, prev_rows = await run_explorer(
            config, client=client, encoder=encoder, sleep=nosleep, now=lambda: when
        )
    assert {row.id for row in new_rows} == {"example:old", "example:new"}
    assert prev_rows == []
    assert search.calls[0].request.headers["user-agent"] == "Ada (ada@example.com)"
    assert encoder.calls
    out = _reports(config)
    assert (out / "job-explorer-2026-09-15T013600Z.html").is_file()
    assert (out / "job-explorer-2026-09-15T013600Z.json").is_file()


@respx.mock
async def test_unchanged_resumes_skip_detail_for_old_id(tmpdir, write_cli_config) -> None:
    resume = write_docx(tmpdir.join("r.docx"), "Python")
    from job_explorer.matching import fingerprint_file

    fp = fingerprint_file(resume)
    config = load_config(write_cli_config(resume), env={})
    respx.get("https://example.com/search").mock(return_value=httpx.Response(200, json=SEARCH))
    detail_old = respx.get("https://example.com/jobs/old").mock(
        return_value=httpx.Response(200, json={"description": "should not fetch"})
    )
    respx.get("https://example.com/jobs/new").mock(
        return_value=httpx.Response(200, json={"description": "fresh python"})
    )
    out = _reports(config)
    out.mkdir(parents=True, exist_ok=True)
    seed = ScoredPosition(
        id="example:old",
        title="Old job",
        url="https://example.com/jobs/old",
        source_id="example",
        scores={"primary": 42.0},
    )
    (out / "job-explorer-state.json").write_text(
        encode_state({"primary": fp}, [seed]),
        encoding="utf-8",
    )
    encoder = FakeEncoder({"Python": [1.0, 0.0], "fresh python": [1.0, 0.0]})
    async with httpx.AsyncClient(headers={"User-Agent": config.user_agent}) as client:
        new_rows, prev_rows = await run_explorer(
            config, client=client, encoder=encoder, sleep=nosleep
        )
    assert detail_old.call_count == 0
    assert [row.id for row in prev_rows] == ["example:old"]
    assert prev_rows[0].scores["primary"] == 42.0
    assert [row.id for row in new_rows] == ["example:new"]


@respx.mock
async def test_changed_resume_refetches_old_id(tmpdir, write_cli_config) -> None:
    resume = write_docx(tmpdir.join("r.docx"), "Python")
    config = load_config(write_cli_config(resume), env={})
    respx.get("https://example.com/search").mock(return_value=httpx.Response(200, json=SEARCH))
    detail_old = respx.get("https://example.com/jobs/old").mock(
        return_value=httpx.Response(200, json={"description": "legacy"})
    )
    respx.get("https://example.com/jobs/new").mock(
        return_value=httpx.Response(200, json={"description": "fresh python"})
    )
    out = _reports(config)
    out.mkdir(parents=True, exist_ok=True)
    seed = ScoredPosition(
        id="example:old",
        title="Old job",
        url="https://example.com/jobs/old",
        source_id="example",
        scores={"primary": 42.0},
    )
    (out / "job-explorer-state.json").write_text(
        encode_state({"primary": "sha256:old-bytes"}, [seed]),
        encoding="utf-8",
    )
    encoder = FakeEncoder(
        {"Python": [1.0, 0.0], "legacy": [0.2, 0.8], "fresh python": [1.0, 0.0]}
    )
    async with httpx.AsyncClient(headers={"User-Agent": config.user_agent}) as client:
        _new, prev_rows = await run_explorer(
            config, client=client, encoder=encoder, sleep=nosleep
        )
    assert detail_old.call_count == 1
    assert prev_rows[0].id == "example:old"
    assert prev_rows[0].scores["primary"] != 42.0
