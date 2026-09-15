from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from job_explorer.models import PreviousState
from job_explorer.state import decode_state, merge_previous_states

logger = logging.getLogger(__name__)

PREVIOUS_JSON_LIMIT = 3
STAMP_FORMAT = "%Y-%m-%dT%H%M%SZ"
_STAMP_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{6}Z)")


def report_stamp(when: datetime) -> str:
    aware = when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).strftime(STAMP_FORMAT)


def json_filename(stamp: str) -> str:
    return f"job-explorer-{stamp}.json"


def html_filename(stamp: str) -> str:
    return f"job-explorer-{stamp}.html"


def resolve_reports_dir(config_dir: str, reports_dir: str) -> Path:
    path = Path(reports_dir).expanduser()
    if not path.is_absolute():
        path = Path(config_dir) / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sort_key(path: Path) -> float:
    match = _STAMP_RE.search(path.name)
    if match:
        try:
            parsed = datetime.strptime(match.group(1), STAMP_FORMAT).replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            pass
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def list_state_jsons(directory: Path) -> list[Path]:
    files = [path for path in directory.glob("*.json") if path.is_file()]
    files.sort(key=lambda path: (_sort_key(path), path.name), reverse=True)
    return files


def load_previous_state(directory: Path, limit: int = PREVIOUS_JSON_LIMIT) -> PreviousState:
    states = []
    for path in list_state_jsons(directory)[:limit]:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("ignoring unreadable job-explorer state %s: %s", path, exc)
            continue
        states.append(decode_state(text))
    return merge_previous_states(states)


def write_report(
    directory: Path,
    *,
    html: str,
    state_json: str,
    when: datetime,
) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = report_stamp(when)
    html_path = directory / html_filename(stamp)
    json_path = directory / json_filename(stamp)
    html_path.write_text(html, encoding="utf-8")
    json_path.write_text(state_json, encoding="utf-8")
    return html_path, json_path
