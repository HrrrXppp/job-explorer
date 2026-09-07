from __future__ import annotations

import httpx
import pytest
import respx

from job_explorer.crawler import crawl_source, extract_description, extract_items, send_request
from job_explorer.models import DetailSpec, HttpRequest, ItemsSpec, Source
from tests.conftest import nosleep

SEARCH_JSON = {"results": [{"id": "123", "title": "Backend", "html_url": "https://example.com/jobs/123"}]}
DETAIL_JSON = {"description": "Need Python"}
JSON_BODY = """
{
  "results": [
    {"id": "123", "title": "Backend", "html_url": "/jobs/123"},
    {"id": "456", "title": "Frontend", "html_url": "https://example.com/jobs/456"}
  ]
}
"""
HTML_BODY = """
<html><body>
  <article class="job"><a class="title" href="/jobs/1" data-id="1">One</a></article>
  <article class="job"><a class="title" href="/jobs/2" data-id="2">Two</a></article>
</body></html>
"""


def _source(**kwargs) -> Source:
    data = dict(
        id="example",
        search_request=HttpRequest(
            method="GET",
            url="https://example.com/search",
            headers={"Accept": "application/json"},
        ),
        items=ItemsSpec(
            kind="json",
            list="$.results",
            fields={"id": "id", "title": "title", "url": "html_url"},
        ),
        detail_request=DetailSpec(
            request=HttpRequest(method="GET", url="https://example.com/jobs/{id}"),
            description="$.description",
        ),
    )
    data.update(kwargs)
    return Source(**data)


@respx.mock
async def test_search_then_detail_url_and_user_agent() -> None:
    search = respx.get("https://example.com/search").mock(
        return_value=httpx.Response(200, json=SEARCH_JSON)
    )
    detail = respx.get("https://example.com/jobs/123").mock(
        return_value=httpx.Response(200, json=DETAIL_JSON)
    )
    async with httpx.AsyncClient(headers={"User-Agent": "Ada Lovelace (ada@example.com)"}) as client:
        items = await crawl_source(client, _source(), sleep=nosleep)
    assert items[0].description == "Need Python"
    assert items[0].skipped_detail is False
    assert search.called
    assert detail.called
    assert search.calls[0].request.headers["user-agent"] == "Ada Lovelace (ada@example.com)"
    assert detail.calls[0].request.headers["user-agent"] == "Ada Lovelace (ada@example.com)"


@respx.mock
async def test_skip_detail_ids_makes_no_detail_call() -> None:
    respx.get("https://example.com/search").mock(return_value=httpx.Response(200, json=SEARCH_JSON))
    detail = respx.get("https://example.com/jobs/123").mock(
        return_value=httpx.Response(200, json=DETAIL_JSON)
    )
    async with httpx.AsyncClient() as client:
        items = await crawl_source(
            client,
            _source(),
            skip_detail_ids={"example:123"},
            sleep=nosleep,
        )
    assert detail.call_count == 0
    assert items[0].skipped_detail is True
    assert items[0].description is None


@respx.mock
async def test_retry_on_5xx() -> None:
    sleeps: list[float] = []

    async def record(delay: float) -> None:
        sleeps.append(delay)

    route = respx.get("https://example.com/search").mock(
        side_effect=[
            httpx.Response(500, text="nope"),
            httpx.Response(200, json=SEARCH_JSON),
        ]
    )
    request = HttpRequest(method="GET", url="https://example.com/search")
    async with httpx.AsyncClient() as client:
        response = await send_request(client, request, sleep=record)
    assert response.status_code == 200
    assert route.call_count == 2
    assert sleeps == [0.5]


@respx.mock
async def test_retry_gives_up_with_http_error() -> None:
    respx.get("https://example.com/search").mock(return_value=httpx.Response(503, text="down"))
    request = HttpRequest(method="GET", url="https://example.com/search")
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await send_request(client, request, sleep=nosleep)
    assert exc_info.value.response.status_code == 503


@respx.mock
async def test_detail_cap() -> None:
    respx.get("https://example.com/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": "1", "title": "A", "html_url": "/1"},
                    {"id": "2", "title": "B", "html_url": "/2"},
                ]
            },
        )
    )
    respx.get("https://example.com/jobs/1").mock(return_value=httpx.Response(200, json=DETAIL_JSON))
    respx.get("https://example.com/jobs/2").mock(return_value=httpx.Response(200, json=DETAIL_JSON))
    async with httpx.AsyncClient() as client:
        items = await crawl_source(client, _source(max_detail_requests=1), sleep=nosleep)
    assert items[0].description == "Need Python"
    assert items[1].description == ""
    assert respx.calls.call_count == 2


@respx.mock
async def test_duplicate_search_id_is_warned(caplog) -> None:
    respx.get("https://example.com/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": "123", "title": "Backend", "html_url": "https://example.com/jobs/123"},
                    {"id": "123", "title": "Dup", "html_url": "https://example.com/jobs/123"},
                ]
            },
        )
    )
    respx.get("https://example.com/jobs/123").mock(return_value=httpx.Response(200, json=DETAIL_JSON))
    async with httpx.AsyncClient() as client:
        items = await crawl_source(client, _source(), sleep=nosleep)
    assert len(items) == 1
    assert "duplicate position id example:123" in caplog.text


def test_json_items_and_relative_urls() -> None:
    spec = ItemsSpec(
        kind="json",
        list="$.results",
        fields={"id": "id", "title": "title", "url": "html_url"},
    )
    items = extract_items(JSON_BODY, spec, base_url="https://example.com/search")
    assert [item["id"] for item in items] == ["123", "456"]
    assert items[0]["url"] == "https://example.com/jobs/123"
    assert items[1]["url"] == "https://example.com/jobs/456"


def test_url_template_builds_job_link() -> None:
    spec = ItemsSpec(
        kind="json",
        list="$.results",
        fields={"id": "id", "title": "title"},
        url_template="https://careers.example.com/job/{id}",
    )
    items = extract_items(JSON_BODY, spec)
    assert items[0]["url"] == "https://careers.example.com/job/123"


def test_json_skips_missing_id() -> None:
    body = '{"results": [{"title": "x"}, {"id": "ok", "title": "y"}]}'
    spec = ItemsSpec(kind="json", list="$.results", fields={"id": "id", "title": "title"})
    items = extract_items(body, spec)
    assert [item["id"] for item in items] == ["ok"]


def test_html_items() -> None:
    spec = ItemsSpec(
        kind="html",
        list="article.job",
        fields={
            "id": "a.title@data-id",
            "title": "a.title",
            "url": "a.title@href",
        },
    )
    items = extract_items(HTML_BODY, spec, base_url="https://example.com/")
    assert items[0] == {"id": "1", "title": "One", "url": "https://example.com/jobs/1"}
    assert items[1]["id"] == "2"


def test_description_field_from_detail_json() -> None:
    assert extract_description('{"description": "Build APIs"}', "$.description", kind="json") == "Build APIs"


def test_description_strips_html_in_json() -> None:
    body = '{"description": "<p style=\\"margin: 0\\">&nbsp;We have an opportunity</p>"}'
    assert extract_description(body, "$.description", kind="json") == "We have an opportunity"


def test_description_field_from_detail_html() -> None:
    html = "<html><div class='desc'>Hello <b>world</b></div></html>"
    assert "Hello" in extract_description(html, "div.desc", kind="html")
