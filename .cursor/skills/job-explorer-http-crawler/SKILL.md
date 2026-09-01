---
name: job-explorer-http-crawler
description: >-
  Defines config.json HTTP request lists and per-source extract/detail rules
  for job-explorer. Use when adding sources, search/detail requests, JSONPath
  or CSS extract fields, pagination, or crawler tests.
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
    "description": {
      "kind": "json",
      "path": "$.description"
    }
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
- Execute with `httpx.Client` (timeout, follow redirects off unless
  `follow_redirects: true`).

## Item extract (`items`)

`kind` is `json` or `html`.

**json**

- `list`: JSONPath to the array of job objects.
- `fields`: map of output name → JSONPath **relative to each item** (or `$`
  for the item itself).

**html**

- `list`: CSS selector for each job card.
- `fields`: output name → `{ "selector": "...", "attr": "href" | "text" }`.
  `attr` default `text`. Resolve relative URLs against the search URL.

Skip items missing `id`. Log and continue on a single item parse error.

## Detail request

Templates in `url`, `headers`, `query`, and `body` substitute `{id}`,
`{title}`, `{url}`, and any extra `fields` keys.

`description` after the detail response:

| kind | rule |
|------|------|
| `json` | `path` JSONPath; join list values with newline |
| `html` | `selector` CSS; `attr` text or attribute |
| `regex` | `pattern` on response text; group 1 or 0 |
| `field` | use already-extracted item field (no extra HTTP) |

If `detail_request` is omitted, description comes from `items.fields.description`
(search payload only).

## Pagination (optional)

```json
"pagination": {
  "kind": "page_query",
  "param": "page",
  "start": 1,
  "max_pages": 5
}
```

Supported `kind` values: `page_query` (increment query param), `none` (default).
Stop early when a page yields zero items.

## Execution rules

- Cap detail requests per source (`max_detail_requests`, default 100).
- Deduplicate by position id before matching.
- Retries: 3 attempts, exponential backoff, only on 429/5xx.
- **Skip detail HTTP** for ids in `skip_detail_ids` (old items + unchanged
  resumes). Crawler still returns those items from search (id, title, url)
  without a description; CLI fills scores from email cache.
- Tests: fixture bodies + `respx`; assert exact detail URLs and extracted
  description text. Assert no detail call when id is in `skip_detail_ids`.
  No live fetches.

## Config interpolation

Replace `${NAME}` in any request string with `os.environ[NAME]`. Missing var
→ fail at config load with a clear error. Never log interpolated secret values.
