# Implementation plan — job explorer Python script

This is the deliverable for [issue #1](https://github.com/HrrrXppp/job-explorer/issues/1): a concrete plan, not the implementation itself.

Decisions locked from discussion:

- Sources are **HTTP request lists** in `config.json`. The script executes them, extracts items with **per-source fields/rules**, then issues **detail requests**.
- Matching: local **sentence-transformers** (default `all-MiniLM-L6-v2`).
- Resumes: **DOCX** files on disk, paths in `config.json`.
- Mail: **Gmail API**, user OAuth (**client id/secret + refresh token** in env).
- Stateless: previous positions and resume fingerprints come from the **last email**, not disk.
- **Skip detail HTTP** for old items when resumes are unchanged ([comment](https://github.com/HrrrXppp/job-explorer/issues/1#issuecomment-5488073881)).
- **User-Agent** is configured once in `config.json` and applied to all HTTP requests ([comment](https://github.com/HrrrXppp/job-explorer/issues/1#issuecomment-5535027740)).

## 1. Goal

A Python CLI that, on each run:

1. Loads `config.json` (sources + resumes) and secrets from the environment.
2. Reads the last Gmail report (positions, scores, resume fingerprints; empty if none).
3. Executes each source’s **search** HTTP request(s) and parses job items.
4. Issues **detail** requests only when required (new item, or resumes changed, or no cached row). Unchanged resumes + old item → skip detail; reuse last scores.
5. Scores fetched descriptions against resumes with a local embedding model.
6. Sends one Gmail message: positions split into **new** vs **previous**, each group ordered by match percent descending.

No database, no `seen.json`, no cache of prior runs.

## 2. Repository layout

```
pyproject.toml
config.json
config.example.json
src/job_explorer/
  __init__.py
  cli.py
  config.py
  models.py
  crawler.py
  matching.py
  gmail_client.py
  report.py
  state.py
tests/
  conftest.py
  fixtures/          # sample JSON/HTML/docx
  test_config.py
  test_crawler.py
  test_matching.py
  test_state.py
  test_report.py
  test_gmail_client.py
  test_cli.py
```

Package install: `uv sync --extra dev`. Entry: `python -m job_explorer` / console script `job-explorer`.

Python **3.11+**. License remains Apache-2.0.

## 3. Configuration

### 3.1 `config.json` (non-secret)

```json
{
  "user_agent": "Your Name (you@example.com) — open to backend roles",
  "resumes": [
    { "id": "primary", "path": "resumes/primary.docx" }
  ],
  "matching": {
    "model": "sentence-transformers/all-MiniLM-L6-v2"
  },
  "email": {
    "to": ["me@example.com"]
  },
  "sources": [
    {
      "id": "example",
      "search_request": {
        "method": "GET",
        "url": "https://example.com/search",
        "headers": {
          "Accept": "application/json",
          "Authorization": "Bearer ${API_TOKEN}"
        },
        "query": { "q": "python" }
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
        "headers": { "Accept": "application/json" },
        "description": "$.description"
      }
    }
  ]
}
```

- `${ENV_VAR}` interpolation in request strings; missing vars fail at load.
- Position id = `{source.id}:{item.id}`.
- `items.kind`: `json` (JSONPath) or `html` (CSS selector). Field values are
  strings; HTML may use `selector@attr`. `fields.id` names the item id field.
- `detail_request` URL/headers/query/body templates substitute `{id}` and other extracted fields.
- `detail_request.description`: field path on the detail body (JSONPath or CSS).
- No pagination object — the search request includes any max-items parameter.
- Optional `max_detail_requests` per source (default 100).
- `user_agent`: single string used as the HTTP `User-Agent` on every search
  and detail request (self-advertising). Per-source headers may
  override `User-Agent` for that request only.
- Models are **Pydantic** (not dataclasses) unless the user asks for maximum performance.
- Package and lock with **uv** (`uv.lock` committed).

Commit `config.json` when it has no secrets (Gmail/API keys stay in `.env`). Resume files stay local / gitignored.

### 3.2 Environment variables (secrets)

| Variable | Purpose |
|----------|---------|
| `GMAIL_CLIENT_ID` | OAuth client id |
| `GMAIL_CLIENT_SECRET` | OAuth client secret |
| `GMAIL_REFRESH_TOKEN` | User refresh token |
| `GMAIL_USER` | Mailbox (default from/to) |
| source-specific vars | Only via `${…}` in request fields |

Gmail OAuth scopes: `gmail.send` and `gmail.readonly`.

## 4. Runtime pipeline

```
validate config + env
→ Gmail: latest message with subject [job-explorer] + attachment job-explorer-state.json
→ previous = decoded v2 state (or ∅)
→ resume_fingerprints = SHA-256 of each resume file
→ resumes_unchanged = fingerprints equal previous.resume_fingerprints (same keys and hashes)
→ for each source: search HTTP → extract items
→ skip_detail_ids = { id | id in previous.positions AND resumes_unchanged AND cached row exists }
→ detail HTTP for items not in skip_detail_ids → embed + score those
→ previous section rows: cached scores for skip_detail_ids; newly scored for others still in previous set
→ new = id ∉ previous ids; previous = id ∈ previous ids (among this run’s search hits)
→ send multipart Gmail: HTML + state v2 (current fingerprints + all this-run positions)
```

HTTP client: `httpx.AsyncClient`. `@retry_http` only retries; the request function decides what is retryable (429/5xx). Cap detail requests. One item parse failure logs and continues. Duplicate ids log a warning.

### 4.1 Skip detail (old item + old resumes)

From issue comment: *Old items shouldn't processed with detail request if resumes are old too.*

| Search hit | Resumes vs last email | Detail HTTP |
|------------|----------------------|-------------|
| New id | any | yes, then match |
| Old id | unchanged (fingerprints match) | **no** — reuse cached title/url/scores |
| Old id | changed, added, removed, or missing fingerprints/cache | yes, then re-match |

Search always runs. Jobs that disappeared from search are not listed. Do not store full descriptions in the email (size); if resumes change, re-fetch details.

## 5. Email format

- **Subject:** `[job-explorer] {n_new} new, {n_prev} previous · {UTC date}`
- **HTML body:** section **New positions**, then **Previous positions**. Each row: match %, title (link), source id, best resume id, short snippet when a description was fetched this run. Empty section still shown as “None”.
- **Attachment:** `job-explorer-state.json` (version 2)

```json
{
  "version": 2,
  "resume_fingerprints": { "primary": "sha256:ab…" },
  "positions": [
    {
      "id": "example:123",
      "title": "Backend engineer",
      "url": "https://example.com/jobs/123",
      "source_id": "example",
      "scores": { "primary": 87.5 }
    }
  ]
}
```

First run (no prior mail) → all positions **new**. Corrupt attachment → warn, treat previous as empty, still send. Legacy v1 `{ "version": 1, "position_ids": [...] }` → classify new/previous but **do not skip** details.

## 6. Matching details

- python-docx paragraph join.
- Resume fingerprint: SHA-256 of file bytes, stored on the email for the next run.
- Default model `sentence-transformers/all-MiniLM-L6-v2`; override in config.
- Encode each resume once; encode each **fetched** unique description once (skipped old items are not re-embedded).
- Multi-resume: report best % and resume id; include other scores in HTML if more than one resume.

## 7. Dependencies (`pyproject.toml`)

Runtime: `httpx`, `jsonpath-ng`, `beautifulsoup4`, `python-docx`, `sentence-transformers`, `google-api-python-client`, `google-auth`, `pydantic`.

Dev: `pytest`, `pytest-asyncio`, `respx` or `pytest-httpx`, `pytest-cov`.

## 8. Test plan (pytest)

| Area | What to prove |
|------|----------------|
| config | valid example loads; missing `${VAR}` errors; schema errors |
| crawler | JSONPath + CSS fixtures; search then exact detail URLs; **no** detail call for `skip_detail_ids`; 5xx retry decorator; cap; duplicate-id warning |
| matching | fake encoder vectors → known percents; docx text extract; empty description → 0.0; file SHA-256 fingerprint |
| state | JSON v2 round-trip; v1 compat (no skip); new vs previous split; fingerprint equality |
| report | both headings; order by %; attachment name |
| gmail | mocked discovery client: list/get/send; zero messages; bad JSON |
| cli | injected fakes: unchanged resumes + old id → zero detail HTTP; changed resume → detail for old id |

No live Gmail or live job HTTP in default CI.

## 9. Implementation order

1. `models` + `config` load/validate + example config.
2. `extract` + unit tests with fixtures.
3. `crawler` + mocked HTTP tests.
4. `matching` (docx + mocked embeddings).
5. `state` + `report`.
6. `gmail_client` (mocked).
7. `cli` orchestration + `test_cli`.
8. README: config, env, one-time Gmail OAuth to obtain refresh token, how to run.

## 10. Non-goals (this issue / first version)

- Site-specific hard-coded scrapers.
- Disk/database of seen jobs.
- Cloud LLM APIs.
- Web UI, scheduler packaging, Docker (can follow later).

## 11. Open items (do not block this plan)

- Exact list of production sources (each is a `sources[]` entry when implementing).
- Whether `email.to` is a list in config or always `GMAIL_USER` only — both supported (`email.to` optional; default `GMAIL_USER`).
- CI: cache HF model vs mock-only (default mock-only).
