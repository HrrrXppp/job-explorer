from __future__ import annotations

import asyncio
import functools
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from jsonpath_ng.ext import parse as jsonpath_parse

from job_explorer.models import CrawledItem, HttpRequest, ItemsSpec, KeepIfSpec, Source
from job_explorer.report import html_to_text

logger = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}
TEMPLATE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
SleepFn = Callable[[float], Awaitable[None]]


class RequestFailed(RuntimeError):
    """A search or detail HTTP request failed; the run should stop."""


class RetryableError(Exception):
    """Raised by the request function when the decorator should try again."""


def retry_http(*, attempts: int = 3) -> Callable:
    def decorate(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            sleep: SleepFn = kwargs.pop("sleep", None) or asyncio.sleep
            delay = 0.5
            for attempt in range(attempts):
                try:
                    return await func(*args, **kwargs)
                except RetryableError as exc:
                    if attempt == attempts - 1:
                        raise RequestFailed(str(exc)) from exc
                    logger.warning("retrying after %s", exc)
                    await sleep(delay)
                    delay *= 2
            raise AssertionError("retry loop exited without result")

        return wrapper

    return decorate


def apply_templates(value: Any, fields: dict[str, str]) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            if key in fields:
                return str(fields[key])
            return match.group(0)

        return TEMPLATE_RE.sub(repl, value)
    if isinstance(value, list):
        return [apply_templates(item, fields) for item in value]
    if isinstance(value, dict):
        return {k: apply_templates(v, fields) for k, v in value.items()}
    return value


@retry_http()
async def send_request(client: httpx.AsyncClient, request: HttpRequest) -> httpx.Response:
    try:
        response = await client.request(**_httpx_kwargs(request))
    except httpx.RequestError as exc:
        raise RequestFailed(f"{request.method} {request.url} failed: {exc}") from exc
    if response.status_code in RETRY_STATUSES:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RetryableError(
                f"{request.method} {request.url} failed: HTTP {response.status_code}"
            ) from exc
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RequestFailed(
            f"{request.method} {request.url} failed: HTTP {response.status_code}"
        ) from exc
    return response


def _httpx_kwargs(request: HttpRequest) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "method": request.method,
        "url": request.url,
        "headers": request.headers or None,
        "follow_redirects": request.follow_redirects,
    }
    if request.query:
        kwargs["params"] = request.query
    if request.body is None:
        return kwargs
    if isinstance(request.body, (dict, list)):
        kwargs["json"] = request.body
    else:
        kwargs["content"] = request.body if isinstance(request.body, bytes) else str(request.body)
    return kwargs


async def crawl_source(
    client: httpx.AsyncClient,
    source: Source,
    *,
    skip_detail_ids: set[str] | None = None,
    sleep: SleepFn = asyncio.sleep,
) -> list[CrawledItem]:
    skip = skip_detail_ids or set()
    found_items = await _found_items(client, source, sleep=sleep)
    seen: set[str] = set()
    crawled: list[CrawledItem | None] = []
    pending: list[tuple[int, dict[str, str]]] = []
    detail_count = 0
    for item in found_items:
        position_id = f"{source.id}:{item['id']}"
        if position_id in seen:
            logger.warning("duplicate position id %s", position_id)
            continue
        seen.add(position_id)
        title = item.get("title") or ""
        url = item.get("url") or ""
        if source.detail_request is None:
            crawled.append(
                CrawledItem(
                    id=position_id,
                    source_id=source.id,
                    title=title,
                    url=url,
                    description=html_to_text(item.get("description") or ""),
                    skipped_detail=False,
                )
            )
            continue
        if position_id in skip:
            crawled.append(
                CrawledItem(
                    id=position_id,
                    source_id=source.id,
                    title=title,
                    url=url,
                    description=None,
                    skipped_detail=True,
                )
            )
            continue
        if detail_count >= source.max_detail_requests:
            logger.warning("max_detail_requests reached for source %s", source.id)
            crawled.append(
                CrawledItem(
                    id=position_id,
                    source_id=source.id,
                    title=title,
                    url=url,
                    description="",
                    skipped_detail=False,
                )
            )
            continue
        crawled.append(None)
        pending.append((len(crawled) - 1, item))
        detail_count += 1
    if pending:
        for index, item in pending:
            description = await _fetch_description(client, source, item, sleep=sleep)
            crawled[index] = CrawledItem(
                id=f"{source.id}:{item['id']}",
                source_id=source.id,
                title=item.get("title") or "",
                url=item.get("url") or "",
                description=description,
                skipped_detail=False,
            )
    return [row for row in crawled if row is not None]


async def crawl_all(
    client: httpx.AsyncClient,
    sources: list[Source],
    *,
    skip_detail_ids: set[str] | None = None,
    sleep: SleepFn = asyncio.sleep,
) -> list[CrawledItem]:
    items: list[CrawledItem] = []
    seen: set[str] = set()
    for source in sources:
        batch = await crawl_source(
            client, source, skip_detail_ids=skip_detail_ids, sleep=sleep
        )
        for item in batch:
            if item.id in seen:
                logger.warning("duplicate position id %s", item.id)
                continue
            seen.add(item.id)
            items.append(item)
    return items


async def _found_items(
    client: httpx.AsyncClient,
    source: Source,
    *,
    sleep: SleepFn,
) -> list[dict[str, str]]:
    response = await send_request(client, source.search_request, sleep=sleep)
    return extract_items(
        response.text,
        source.items,
        content_type=response.headers.get("content-type", ""),
        base_url=str(response.url),
        source_id=source.id,
    )


async def _fetch_description(
    client: httpx.AsyncClient,
    source: Source,
    item: dict[str, str],
    *,
    sleep: SleepFn,
) -> str:
    assert source.detail_request is not None
    templated = apply_templates(
        {
            "method": source.detail_request.request.method,
            "url": source.detail_request.request.url,
            "headers": source.detail_request.request.headers,
            "query": source.detail_request.request.query,
            "body": source.detail_request.request.body,
            "follow_redirects": source.detail_request.request.follow_redirects,
        },
        item,
    )
    request = HttpRequest(
        method=templated["method"],
        url=templated["url"],
        headers=templated["headers"],
        query=templated["query"],
        body=templated["body"],
        follow_redirects=bool(templated["follow_redirects"]),
    )
    response = await send_request(client, request, sleep=sleep)
    return extract_description(
        response.text,
        source.detail_request.description,
        kind=source.items.kind,
        base_url=str(response.url),
        content_type=response.headers.get("content-type", ""),
    )


def split_field_ref(ref: str) -> tuple[str, str]:
    """Config field value is a path/selector, optionally `selector@attr`."""
    if "@" in ref:
        selector, attr = ref.rsplit("@", 1)
        return selector, attr or "text"
    return ref, "text"


def jsonpath_values(data: Any, expr: str) -> list[Any]:
    path = expr if expr.startswith("$") else f"$.{expr}"
    return [match.value for match in jsonpath_parse(path).find(data)]


def jsonpath_one(data: Any, expr: str) -> Any:
    values = jsonpath_values(data, expr)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return values


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(stringify(item) for item in value if item is not None)
    if isinstance(value, (dict, bool, int, float)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _is_xml_markup(body: str, content_type: str = "") -> bool:
    ctype = content_type.lower()
    if "html" in ctype:
        return False
    if any(token in ctype for token in ("xml", "rss", "atom")):
        return True
    stripped = body.lstrip()
    return stripped.startswith(("<?xml", "<rss", "<feed", "<RDF"))


def _soup(body: str, content_type: str = "") -> BeautifulSoup:
    features = "lxml-xml" if _is_xml_markup(body, content_type) else "lxml"
    return BeautifulSoup(body, features)


def extract_items(
    body: str,
    spec: ItemsSpec,
    *,
    content_type: str = "",
    base_url: str = "",
    source_id: str = "",
) -> list[dict[str, str]]:
    if spec.kind == "json":
        items = _extract_json_items(body, spec, base_url=base_url, source_id=source_id)
    else:
        items = _extract_html_items(
            body, spec, content_type=content_type, base_url=base_url, source_id=source_id
        )
    if spec.url_template:
        for item in items:
            item["url"] = apply_templates(spec.url_template, item)
    groups = spec.keep_if_groups()
    if groups:
        items = [
            item
            for item in items
            if all(item_matches_keep_if(item, group) for group in groups)
        ]
    return items


def item_matches_keep_if(item: dict[str, str], keep_if: KeepIfSpec) -> bool:
    blob = " ".join(item.get(name, "") for name in keep_if.fields).lower()
    return any(needle.lower() in blob for needle in keep_if.contains_any)


def extract_description(
    body: str,
    field: str,
    *,
    kind: str,
    base_url: str = "",
    content_type: str = "",
) -> str:
    if kind == "json":
        data = json.loads(body)
        return html_to_text(stringify(jsonpath_one(data, field)))
    soup = _soup(body, content_type)
    selector, attr = split_field_ref(field)
    target = soup.select_one(selector) if selector else soup
    if target is None:
        return ""
    if attr == "text":
        return html_to_text(target.get_text("\n", strip=True))
    value = target.get(attr) or ""
    if isinstance(value, list):
        value = " ".join(str(part) for part in value)
    if base_url and value:
        return urljoin(base_url, str(value))
    return str(value)


def _extract_json_items(
    body: str, spec: ItemsSpec, *, base_url: str, source_id: str = ""
) -> list[dict[str, str]]:
    data = json.loads(body)
    matches = jsonpath_values(data, spec.list)
    if len(matches) == 1 and isinstance(matches[0], list):
        rows = matches[0]
    else:
        rows = matches
    items: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        try:
            parsed = _fields_from_json_row(row, spec, base_url=base_url)
        except Exception:
            logger.warning(
                "skipping %s item %s: parse error", source_id or "source", index, exc_info=True
            )
            continue
        if not parsed.get("id"):
            logger.warning("skipping %s item %s: missing id", source_id or "source", index)
            continue
        items.append(parsed)
    return items


def _fields_from_json_row(row: Any, spec: ItemsSpec, *, base_url: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, field_ref in spec.fields.items():
        expr, _attr = split_field_ref(field_ref)
        value = stringify(jsonpath_one(row, expr))
        if name == "url" and value:
            value = urljoin(base_url, value)
        out[name] = value
    return out


def _extract_html_items(
    body: str,
    spec: ItemsSpec,
    *,
    content_type: str = "",
    base_url: str,
    source_id: str = "",
) -> list[dict[str, str]]:
    soup = _soup(body, content_type)
    cards = soup.select(spec.list)
    items: list[dict[str, str]] = []
    for index, card in enumerate(cards):
        try:
            parsed: dict[str, str] = {}
            for name, field_ref in spec.fields.items():
                parsed[name] = _html_field(
                    card, field_ref, base_url=base_url if name == "url" else ""
                )
        except Exception:
            logger.warning(
                "skipping %s item %s: parse error", source_id or "source", index, exc_info=True
            )
            continue
        if not parsed.get("id"):
            logger.warning("skipping %s item %s: missing id", source_id or "source", index)
            continue
        items.append(parsed)
    return items


def _html_field(node: Any, field_ref: str, *, base_url: str) -> str:
    selector, attr = split_field_ref(field_ref)
    target = node.select_one(selector) if selector else node
    if target is None:
        return ""
    if attr == "text":
        value = target.get_text(" ", strip=True)
    else:
        value = target.get(attr) or ""
        if isinstance(value, list):
            value = " ".join(str(part) for part in value)
        value = str(value)
    if base_url and value:
        value = urljoin(base_url, value)
    return value
