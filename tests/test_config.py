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


OPERATOR = Path(__file__).resolve().parents[1] / "config.json"


def test_operator_config_limits_remote_search_to_united_states() -> None:
    raw = json.loads(OPERATOR.read_text(encoding="utf-8"))
    config = parse_config(raw, config_dir=".")
    by_id = {source.id: source for source in config.sources}
    assert "worldwide" not in by_id["himalayas"].search_request.query
    assert by_id["himalayas"].search_request.query["country"] == "US"
    assert by_id["jobicy"].search_request.query["geo"] == "usa"
    assert by_id["4dayweek"].search_request.query["country"] == "United States"
    assert "locations:USA" in by_id["workingnomads"].search_request.body["query"]["query_string"]["query"]
    assert by_id["remotive"].items.keep_if is not None
    assert by_id["remoteok"].items.keep_if is not None
    assert by_id["netflix"].search_request.query["location"] == "USA - Remote"
    assert by_id["netflix"].search_request.query["query"] == "python"
    assert "2fcb99c455831013ea52fb338f2932d8" in by_id["nvidia"].search_request.body["appliedFacets"]["locationHierarchy1"]
    assert isinstance(by_id["stripe"].items.keep_if, list)
    assert by_id["vanguard"].search_request.body["searchText"] == "Python"
    assert "b9f1251c6ce51052658919a6dcd898d1" in by_id["vanguard"].search_request.body["appliedFacets"]["locations"]
    assert by_id["comcast"].search_request.body["appliedFacets"]["locations"]
    assert "38d640cf23a8018e1b28496e7f273239" in by_id["comcast"].search_request.body["appliedFacets"]["locations"]
    assert "247bad0b5244013e714617da39329502" in by_id["comcast_remote"].search_request.body["appliedFacets"]["locations"]
    assert by_id["cencora"].search_request.body["keywords"] == "python"
    assert "Conshohocken" in by_id["cencora"].search_request.body["selected_fields"]["city"]
    assert by_id["cencora_remote"].search_request.body["selected_fields"]["city"] == ["Remote"]
    assert "United States" in by_id["cencora_remote"].items.keep_if.contains_any
    assert by_id["gsk"].search_request.body["searchText"] == "Python"
    assert "90793f76afe70136bdc7d0ebdf14c8bb" in by_id["gsk"].search_request.body["appliedFacets"]["locations"]
