from __future__ import annotations

from job_explorer.models import CachedPosition, PreviousState, ScoredPosition
from job_explorer.state import decode_state, encode_state, resumes_unchanged, skip_detail_ids, split_new_previous


def _row(pid: str, percent: float) -> ScoredPosition:
    return ScoredPosition(
        id=pid,
        title=pid,
        url="",
        source_id="s",
        scores={"r": percent},
    )


def test_v2_round_trip() -> None:
    rows = [_row("example:1", 80.0)]
    raw = encode_state({"primary": "sha256:abc"}, rows)
    state = decode_state(raw)
    assert state.version == 2
    assert state.resume_fingerprints["primary"] == "sha256:abc"
    assert state.positions[0].id == "example:1"
    assert state.positions[0].scores["r"] == 80.0
    assert "example:1" in state.position_ids


def test_v1_compat_does_not_skip() -> None:
    state = decode_state('{"version": 1, "position_ids": ["example:1"]}')
    assert state.position_ids == {"example:1"}
    assert skip_detail_ids(state, {"primary": "sha256:x"}) == set()


def test_fingerprint_equality() -> None:
    current = {"a": "sha256:1", "b": "sha256:2"}
    assert resumes_unchanged(current, dict(current))
    assert not resumes_unchanged(current, {"a": "sha256:1"})
    assert not resumes_unchanged(current, {"a": "sha256:1", "b": "sha256:9"})
    assert not resumes_unchanged({}, current)


def test_skip_when_resumes_and_cache_match() -> None:
    previous = PreviousState(
        version=2,
        resume_fingerprints={"primary": "sha256:aa"},
        positions=[
            CachedPosition(
                id="example:1",
                title="T",
                url="u",
                source_id="example",
                scores={"primary": 10.0},
            )
        ],
        position_ids={"example:1"},
    )
    assert skip_detail_ids(previous, {"primary": "sha256:aa"}) == {"example:1"}
    assert skip_detail_ids(previous, {"primary": "sha256:zz"}) == set()


def test_split_new_previous_order() -> None:
    rows = [_row("old", 10.0), _row("new-hi", 90.0), _row("new-lo", 20.0)]
    new_rows, prev_rows = split_new_previous(rows, {"old"})
    assert [r.id for r in new_rows] == ["new-hi", "new-lo"]
    assert [r.id for r in prev_rows] == ["old"]


def test_corrupt_json_is_empty() -> None:
    state = decode_state("not-json{")
    assert state.position_ids == set()
    assert state.positions == []
