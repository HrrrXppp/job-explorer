---
name: job-explorer
description: >-
  Implements and extends the job-explorer Python CLI from GitHub issue #1:
  crawl job sources from config.json HTTP request lists, match DOCX resumes
  with a local sentence-transformers model, email a ranked new/previous report
  via Gmail API, remain stateless (previous positions come from the last three emails).
  Use when working on this repo, config.json, pytest, the CLI pipeline, or
  issue #1.
---

# Job explorer

Issue: https://github.com/HrrrXppp/job-explorer/issues/1

This repo is a **stateless** Python CLI. Do not add a database, cache file, or
local "seen jobs" store. Previous positions, scores, and resume fingerprints
come only from the last three Gmail reports (newest fingerprints and cached
rows win; position ids are the union).

## Constraints (must not violate)

- Search sources live in `config.json`. Secrets stay in environment variables.
- Secrets live in environment variables, never in `config.json` or git.
- Resumes are `.docx` files on disk; paths are listed in `config.json`.
- Matching uses a **local** `sentence-transformers` model (default
  `all-MiniLM-L6-v2`). No cloud LLM APIs.
- Email send + previous-state fetch use **Gmail API** with OAuth refresh token
  env vars. See [job-explorer-gmail-state](../job-explorer-gmail-state/SKILL.md).
- Sources are HTTP request lists; each source has rules for extracting items
  and building follow-up detail requests. See
  [job-explorer-http-crawler](../job-explorer-http-crawler/SKILL.md).
- `config.json` `user_agent` is set **once** and applied to every HTTP request
  (search and detail). Use it to advertise the operator. Do not repeat
  User-Agent on each source unless that source must override it.
- Behavior is covered by **pytest**. No live network or live Gmail in CI.
- Use **Pydantic** models everywhere (config, crawl results, email state).
  Do not introduce dataclasses unless the user asks for maximum performance.

## Pipeline

```
load config + env
  -> Gmail: read last three report JSONs and merge (empty if none)
  -> hash each resume file (SHA-256); compare to newest email fingerprints
  -> for each source: search HTTP -> parse items
  -> detail HTTP only when required (see skip rule) -> match those
  -> split new vs previous; sort each group by match % desc
  -> Gmail: send HTML report + machine-readable state MIME part
```

### Skip detail requests ([comment](https://github.com/HrrrXppp/job-explorer/issues/1#issuecomment-5488073881))

Do **not** issue a detail request for a position when **both** are true:

1. **Old item:** its id is in the merged last-three-email position list.
2. **Resumes unchanged:** current SHA-256 of every resume file (keyed by
   resume id) equals `resume_fingerprints` from the newest email that has
   them (same ids, same hashes).

Then reuse the newest cached title, url, source id, and scores for the
**Previous** section. Search requests still run so we know the job is open.

**Always** fetch details and re-score when any of these hold: new position id;
resume added, removed, or file bytes changed; last state missing fingerprints
or the cached row for that id.

If `detail_request` is omitted, there is no extra HTTP — description comes
from `items.fields.description` on the search payload. When a detail request
is present, `description` is the field path (JSONPath or CSS) on that
response.

CLI entry: `python -m job_explorer` (optional `--config path`).

## Package layout

```
src/job_explorer/
  cli.py           # argparse, orchestration only
  config.py        # load/validate config.json; ${ENV} interpolation in headers
  models.py        # Pydantic models (not dataclasses unless asked for max performance)
  crawler.py       # async search + detail HTTP and field extract
  matching.py      # docx text + sentence-transformers scores
  gmail_client.py  # fetch last state, send message
  report.py        # HTML body + state JSON payload
  state.py         # encode/decode fingerprints + cached positions/scores
tests/
config.json
config.example.json
pyproject.toml
```

Keep HTTP, matching, Gmail, and report modules independently testable.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `GMAIL_CLIENT_ID` | OAuth client id |
| `GMAIL_CLIENT_SECRET` | OAuth client secret |
| `GMAIL_REFRESH_TOKEN` | User refresh token (`gmail.send` + `gmail.readonly`) |
| `GMAIL_USER` | Mailbox (from/to default) |

Source-specific API keys may appear only as `${VAR}` placeholders inside
`config.json` request headers/query/body.

## Matching

- Extract text from each resume with `python-docx`.
- Embed once per resume, once per job description.
- Score = `max(0, cosine(resume, job)) * 100`, one decimal.
- If several resumes exist, record **every** resume score; the sort key is the
  **best** score for that position. Email HTML shows best % and which resume
  for matches **above 20%**; ≤ 20% stays in the state attachment only.

## Pytest

- `httpx` + `respx` (or `pytest-httpx`) for HTTP; never hit real job sites.
- Mock Gmail API; test MIME state round-trip and new/previous split.
- Mock `SentenceTransformer.encode` in unit tests; one optional integration
  test marked `@pytest.mark.slow` may load the real tiny model if present.
- Fixture HTML/JSON under `tests/fixtures/`.
- Cover: config validation, extract rules, crawler follow-up URLs, matching
  math, state parse, report sections, CLI with injected fakes.
- Cover skip rule: unchanged resumes + old id → zero detail HTTP; changed
  resume hash → detail HTTP for old ids; new id → detail HTTP.

## Out of scope unless asked

- Persistent disk state, cron installer, web UI, cloud embeddings, scraping
  that ignores `config.json` request rules.

## Related skills

- [job-explorer-http-crawler](../job-explorer-http-crawler/SKILL.md)
- [job-explorer-gmail-state](../job-explorer-gmail-state/SKILL.md)
- [job-explorer-matching](../job-explorer-matching/SKILL.md)
- Issue #1 plan: [implementation-plan.md](implementation-plan.md)
