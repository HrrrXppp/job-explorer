from __future__ import annotations

import httpx
import respx

from job_explorer.cli import run_explorer
from job_explorer.config import load_config
from job_explorer.models import CachedPosition, PreviousState
from job_explorer.state import empty_state
from tests.conftest import nosleep, write_docx
from tests.test_matching import FakeEncoder


class FakeGmail:
    def __init__(self, previous: PreviousState | None = None) -> None:
        self.previous = previous or empty_state()
        self.sent: list[bytes] = []

    def fetch_previous_state(self) -> PreviousState:
        return self.previous

    def send_raw(self, mime_bytes: bytes) -> None:
        self.sent.append(mime_bytes)


SEARCH = {
    "results": [
        {"id": "old", "title": "Old job", "html_url": "https://example.com/jobs/old"},
        {"id": "new", "title": "New job", "html_url": "https://example.com/jobs/new"},
    ]
}


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
    gmail = FakeGmail()
    encoder = FakeEncoder({"Python": [1.0, 0.0], "legacy": [0.0, 1.0], "fresh python": [1.0, 0.0]})
    env = {"GMAIL_USER": "me@example.com"}
    async with httpx.AsyncClient(headers={"User-Agent": config.user_agent}) as client:
        new_rows, prev_rows = await run_explorer(
            config, env=env, client=client, gmail=gmail, encoder=encoder, sleep=nosleep
        )
    assert {row.id for row in new_rows} == {"example:old", "example:new"}
    assert prev_rows == []
    assert gmail.sent
    assert search.calls[0].request.headers["user-agent"] == "Ada (ada@example.com)"
    assert encoder.calls


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
    previous = PreviousState(
        version=2,
        resume_fingerprints={"primary": fp},
        positions=[
            CachedPosition(
                id="example:old",
                title="Old job",
                url="https://example.com/jobs/old",
                source_id="example",
                scores={"primary": 42.0},
            )
        ],
        position_ids={"example:old"},
    )
    gmail = FakeGmail(previous)
    encoder = FakeEncoder({"Python": [1.0, 0.0], "fresh python": [1.0, 0.0]})
    async with httpx.AsyncClient(headers={"User-Agent": config.user_agent}) as client:
        new_rows, prev_rows = await run_explorer(
            config,
            env={"GMAIL_USER": "me@example.com"},
            client=client,
            gmail=gmail,
            encoder=encoder,
            sleep=nosleep,
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
    previous = PreviousState(
        version=2,
        resume_fingerprints={"primary": "sha256:old-bytes"},
        positions=[
            CachedPosition(
                id="example:old",
                title="Old job",
                url="https://example.com/jobs/old",
                source_id="example",
                scores={"primary": 42.0},
            )
        ],
        position_ids={"example:old"},
    )
    gmail = FakeGmail(previous)
    encoder = FakeEncoder(
        {"Python": [1.0, 0.0], "legacy": [0.2, 0.8], "fresh python": [1.0, 0.0]}
    )
    async with httpx.AsyncClient(headers={"User-Agent": config.user_agent}) as client:
        _new, prev_rows = await run_explorer(
            config,
            env={"GMAIL_USER": "me@example.com"},
            client=client,
            gmail=gmail,
            encoder=encoder,
            sleep=nosleep,
        )
    assert detail_old.call_count == 1
    assert prev_rows[0].id == "example:old"
    assert prev_rows[0].scores["primary"] != 42.0
