from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from job_explorer.models import CachedPosition, PreviousState, ScoredPosition

logger = logging.getLogger(__name__)

STATE_VERSION = 2
STATE_FILENAME = "job-explorer-state.json"


def empty_state() -> PreviousState:
    return PreviousState(version=STATE_VERSION, resume_fingerprints={}, positions=[], position_ids=set())


def merge_previous_states(states: Sequence[PreviousState]) -> PreviousState:
    """Newest-first: keep latest fingerprints and latest cached row per id."""
    fingerprints: dict[str, str] = {}
    by_id: dict[str, CachedPosition] = {}
    position_ids: set[str] = set()
    for state in states:
        if not fingerprints and state.resume_fingerprints:
            fingerprints = dict(state.resume_fingerprints)
        for row in state.positions:
            if row.id not in by_id:
                by_id[row.id] = row
        position_ids.update(state.position_ids)
        position_ids.update(row.id for row in state.positions)
    if not fingerprints and not by_id and not position_ids:
        return empty_state()
    return PreviousState(
        version=STATE_VERSION,
        resume_fingerprints=fingerprints,
        positions=list(by_id.values()),
        position_ids=position_ids,
    )


def decode_state(payload: str | bytes | dict) -> PreviousState:
    try:
        if isinstance(payload, dict):
            data = payload
        else:
            text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
            data = json.loads(text)
        if not isinstance(data, dict):
            raise TypeError("state is not an object")
        return PreviousState.model_validate(data)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError, ValidationError) as exc:
        logger.warning("ignoring corrupt job-explorer state: %s", exc)
        return empty_state()


def encode_state(
    fingerprints: Mapping[str, str],
    positions: list[ScoredPosition],
) -> str:
    payload = {
        "version": STATE_VERSION,
        "resume_fingerprints": dict(fingerprints),
        "positions": [
            {
                "id": row.id,
                "title": row.title,
                "url": row.url,
                "source_id": row.source_id,
                "scores": row.scores,
            }
            for row in positions
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def resumes_unchanged(current: Mapping[str, str], previous: Mapping[str, str]) -> bool:
    if not current or not previous:
        return False
    return dict(current) == dict(previous)


def skip_detail_ids(previous: PreviousState, fingerprints: Mapping[str, str]) -> set[str]:
    if not resumes_unchanged(fingerprints, previous.resume_fingerprints):
        return set()
    return {row.id for row in previous.positions}


def cached_by_id(previous: PreviousState) -> dict[str, CachedPosition]:
    return {row.id: row for row in previous.positions}


def split_new_previous(
    rows: list[ScoredPosition],
    previous_ids: set[str],
) -> tuple[list[ScoredPosition], list[ScoredPosition]]:
    new_rows: list[ScoredPosition] = []
    previous_rows: list[ScoredPosition] = []
    for row in rows:
        if row.id in previous_ids:
            previous_rows.append(row)
        else:
            new_rows.append(row)
    new_rows.sort(key=lambda item: item.best_percent, reverse=True)
    previous_rows.sort(key=lambda item: item.best_percent, reverse=True)
    return new_rows, previous_rows
