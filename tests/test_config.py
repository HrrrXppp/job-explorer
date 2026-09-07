from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_explorer.config import ConfigError, load_config, parse_config

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.json"


def test_example_config_loads_with_env() -> None:
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    config = load_config(EXAMPLE, env={"API_TOKEN": "secret-token"})
    source = config.sources[0]
    search = raw["sources"][0]["search_request"]
    items = raw["sources"][0]["items"]
    detail = raw["sources"][0]["detail_request"]
    assert config.user_agent == raw["user_agent"]
    assert config.resumes[0].id == raw["resumes"][0]["id"]
    assert config.resumes[0].path.endswith(raw["resumes"][0]["path"])
    assert config.matching.model == raw["matching"]["model"]
    assert config.email.to == raw["email"]["to"]
    assert source.id == raw["sources"][0]["id"]
    assert source.search_request.method == search["method"]
    assert source.search_request.url == search["url"]
    assert source.search_request.query == search["query"]
    assert source.search_request.headers["Accept"] == search["headers"]["Accept"]
    assert source.search_request.headers["Authorization"] == "Bearer secret-token"
    assert source.items.kind == items["kind"]
    assert source.items.list == items["list"]
    assert source.items.fields == items["fields"]
    assert source.detail_request is not None
    assert source.detail_request.request.method == detail["method"]
    assert source.detail_request.request.url == detail["url"]
    assert source.detail_request.request.headers == detail["headers"]
    assert source.detail_request.description == detail["description"]


def test_missing_env_var_fails() -> None:
    with pytest.raises(ConfigError, match="API_TOKEN"):
        load_config(EXAMPLE, env={})


def test_missing_resumes_fails() -> None:
    with pytest.raises(ConfigError, match="resumes"):
        parse_config({"sources": [{"id": "x"}]}, config_dir=".")


def test_user_agent_required_non_empty() -> None:
    raw = json.loads(EXAMPLE.read_text())
    raw["user_agent"] = "   "
    with pytest.raises(ConfigError, match="user_agent"):
        parse_config(raw, config_dir=".")


def test_default_user_agent_when_omitted() -> None:
    raw = json.loads(EXAMPLE.read_text())
    del raw["user_agent"]
    config = parse_config(raw, config_dir="/tmp")
    assert config.user_agent == "job-explorer/0.1"
