---
name: job-explorer-http-crawler
description: >-
  Defines config.json HTTP request lists and per-source extract/detail rules
  for job-explorer. Use when adding sources, search/detail requests, JSONPath
  or CSS extract fields, or crawler tests.
---

# HTTP crawler (config-driven)

The operator writes **HTTP requests in lists**. The script executes each search
request, extracts job items with **per-source fields/rules**, then issues
**detail requests** built from those fields.

Do not hard-code site adapters (LinkedIn, Indeed, …). New sites = new
`config.json` entries.

## Source object

Each element of `config.json` `"sources"`:

```json
{
  "id": "example",
  "search_request": {
    "method": "GET",
    "url": "https://example.com/search",
    "headers": {"Accept": "application/json", "Authorization": "Bearer ${API_TOKEN}"},
    "query": {"q": "python"},
    "body": null
  },
  "items": {
    "kind": "json",
    "list": "$.results",
    "fields": {
      "id": "id",
      "title": "title",
      "url": "html_url"
    }
  },
  "detail_request": {
    "method": "GET",
    "url": "https://example.com/jobs/{id}",
    "headers": {"Accept": "application/json"},
    "query": {},
    "body": null,
    "description": "$.description"
  }
}
```

Position identity: `{source_id}:{item.id}` (string). Required extract field:
`id`. Recommended: `title`, `url`.

## Search request

- `method`: GET or POST.
- `url`, optional `headers`, `query`, `body` (object → JSON, string → raw).
- Interpolate `{field}` only on **detail** requests (from the item). Search
  requests interpolate `${ENV}` only.
- Execute with `httpx.AsyncClient` (timeout, follow redirects off unless
  `follow_redirects: true`). Search sources and detail requests run concurrently.
- Default `User-Agent` comes from top-level `config.json` `"user_agent"`
  (one value for every request). Per-request `headers["User-Agent"]` overrides
  that default for that request only.

## Item extract (`items`)

`kind` is `json` or `html`.

**json**

- `list`: JSONPath to the array of job objects.
- `fields`: map of output name → JSONPath **relative to each item** (or `$`
  for the item itself).

**html**

- `list`: CSS selector for each job card.
- `fields`: output name → CSS selector string. Optional `@attr` suffix
  (`a.title@href`, `a.title@data-id`). Default attr is `text`.
  Resolve relative URLs against the search URL.

`fields.id` is required: the operator names which field is the item id.

`list` may use a JSONPath filter so preamble objects are never selected.
Remote OK’s feed is a root array whose first object is a legal notice with no
`id` — use `"list": "$[?(@.id)]"`.

Optional `url_template` is filled from extracted fields (`{id}`, `{title}`, …)
when the search payload has no job URL. Example:
`https://careers.example.com/jobs/{id}`.

Optional `keep_if` drops items after extract unless any listed field contains
any of `contains_any` (case-insensitive substring). Use it when the search
HTTP API has no country/location query. Example: keep United States–eligible
remote jobs via a `location` field and needles like `USA`, `United States`,
`Worldwide`. `keep_if.fields` must be keys in `items.fields`.

Skip items missing `id`. Log and continue on a single item parse error.

## Detail request

Templates in `url`, `headers`, `query`, and `body` substitute `{id}`,
`{title}`, `{url}`, and any extra `fields` keys.

`description` is the field that holds the job text on the detail response:
JSONPath when `items.kind` is `json` (`$.description`), CSS (optional
`selector@attr`) when `items.kind` is `html`.

If `detail_request` is omitted, description comes from `items.fields.description`
(search payload only).

Do not add a pagination object. Put a max-items query parameter on the search
request itself if the source API supports it.

## Execution rules

- Cap detail requests per source (`max_detail_requests`, default 100).
- Deduplicate by position id before matching.
- Retries: `@retry_http` only retries; `send_request` raises on 429/5xx so the
  decorator can back off (3 attempts, exponential).
- **Skip detail HTTP** for ids in `skip_detail_ids` (old items + unchanged
  resumes). Crawler still returns those items from search (id, title, url)
  without a description; CLI fills scores from email cache.
- Tests: fixture bodies + `respx`; assert exact detail URLs and extracted
  description text. Assert no detail call when id is in `skip_detail_ids`.
  No live fetches.

## Config interpolation

Replace `${NAME}` in any request string with `os.environ[NAME]`. Missing var
→ fail at config load with a clear error. Never log interpolated secret values.
