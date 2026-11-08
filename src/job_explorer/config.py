from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from job_explorer.models import AppConfig, ResumeSpec

ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(ValueError):
    """Invalid config.json or missing interpolated environment variable."""


def interpolate_str(value: str, env: Mapping[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in env:
            raise ConfigError(f"missing environment variable {name}")
        return env[name]

    return ENV_PATTERN.sub(repl, value)


def interpolate(obj: Any, env: Mapping[str, str]) -> Any:
    if isinstance(obj, str):
        return interpolate_str(obj, env)
    if isinstance(obj, list):
        return [interpolate(item, env) for item in obj]
    if isinstance(obj, dict):
        return {key: interpolate(value, env) for key, value in obj.items()}
    return obj


def load_config(path: str | Path, env: Mapping[str, str] | None = None) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("config.json must be a JSON object")
    data = interpolate(raw, env if env is not None else os.environ)
    return parse_config(data, config_dir=str(config_path.parent))


def parse_config(data: dict[str, Any], *, config_dir: str) -> AppConfig:
    payload = dict(data)
    payload["config_dir"] = config_dir
    try:
        config = AppConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
    resumes = [_resolve_resume(resume, config_dir) for resume in config.resumes]
    return config.model_copy(update={"resumes": resumes})


def _resolve_resume(resume: ResumeSpec, config_dir: str) -> ResumeSpec:
    path = resume.path
    if not os.path.isabs(path):
        path = str(Path(config_dir) / path)
    return resume.model_copy(update={"path": path})
