from __future__ import annotations

from job_explorer.models import CachedPosition, PreviousState, ScoredPosition
from job_explorer.state import (
    decode_state,
    dedupe_scored_by_url,
    encode_state,
    merge_previous_states,
    resumes_unchanged,
    skip_detail_ids,
    split_new_previous,
)


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


def test_dedupe_same_url_from_overlapping_searches() -> None:
    local = ScoredPosition(
        id="dice:97dd345f",
        title="Lead Python developer",
        url="https://www.dice.com/job-detail/97dd345f-b575-421f-8e1a-802a89db2201",
        source_id="dice",
        scores={"primary": 20.2},
    )
    remote = local.model_copy(
        update={
            "id": "dice_remote:97dd345f",
            "source_id": "dice_remote",
            "url": "https://www.Dice.com/job-detail/97dd345f-b575-421f-8e1a-802a89db2201/",
            "scores": {"primary": 55.0},
        }
    )
    other = ScoredPosition(
        id="chase:1",
        title="Other",
        url="https://example.com/jobs/1",
        source_id="chase",
        scores={"primary": 40.0},
    )
    blank_a = ScoredPosition(
        id="a:1",
        title="A",
        url="",
        source_id="a",
        scores={"primary": 10.0},
    )
    blank_b = blank_a.model_copy(update={"id": "b:1", "source_id": "b"})
    rows = dedupe_scored_by_url([local, remote, other, blank_a, blank_b], set())
    assert [row.id for row in rows] == ["dice_remote:97dd345f", "chase:1", "a:1", "b:1"]
    assert rows[0].best_percent == 55.0


def test_dedupe_keeps_previous_id_when_urls_match() -> None:
    local = ScoredPosition(
        id="dice:97dd345f",
        title="Lead Python developer",
        url="https://www.dice.com/job-detail/97dd345f",
        source_id="dice",
        scores={"primary": 20.2},
    )
    remote = local.model_copy(
        update={"id": "dice_remote:97dd345f", "source_id": "dice_remote", "scores": {"primary": 20.2}}
    )
    rows = dedupe_scored_by_url([remote, local], {"dice:97dd345f"})
    assert [row.id for row in rows] == ["dice:97dd345f"]
    new_rows, prev_rows = split_new_previous(rows, {"dice:97dd345f"})
    assert new_rows == []
    assert [row.id for row in prev_rows] == ["dice:97dd345f"]


def test_split_new_previous_order() -> None:
    rows = [_row("old", 10.0), _row("new-hi", 90.0), _row("new-lo", 20.0)]
    new_rows, prev_rows = split_new_previous(rows, {"old"})
    assert [r.id for r in new_rows] == ["new-hi", "new-lo"]
    assert [r.id for r in prev_rows] == ["old"]


def test_corrupt_json_is_empty() -> None:
    state = decode_state("not-json{")
    assert state.position_ids == set()
    assert state.positions == []


def _cached(pid: str, title: str = "T", score: float = 1.0) -> CachedPosition:
    return CachedPosition(
        id=pid,
        title=title,
        url="u",
        source_id="example",
        scores={"primary": score},
    )


def test_merge_previous_states_newest_wins() -> None:
    newest = PreviousState(
        version=2,
        resume_fingerprints={"primary": "sha256:new"},
        positions=[_cached("example:1", title="New title", score=90.0)],
        position_ids={"example:1"},
    )
    middle = PreviousState(
        version=2,
        resume_fingerprints={"primary": "sha256:old"},
        positions=[_cached("example:1", title="Old title", score=10.0), _cached("example:2")],
        position_ids={"example:1", "example:2"},
    )
    oldest = PreviousState(
        version=2,
        resume_fingerprints={"primary": "sha256:older"},
        positions=[_cached("example:3")],
        position_ids={"example:3"},
    )
    merged = merge_previous_states([newest, middle, oldest])
    assert merged.resume_fingerprints == {"primary": "sha256:new"}
    assert {row.id: row.title for row in merged.positions} == {
        "example:1": "New title",
        "example:2": "T",
        "example:3": "T",
    }
    assert merged.position_ids == {"example:1", "example:2", "example:3"}


def test_merge_previous_states_empty() -> None:
    merged = merge_previous_states([PreviousState(), PreviousState()])
    assert merged.positions == []
    assert merged.position_ids == set()
    assert merged.resume_fingerprints == {}
