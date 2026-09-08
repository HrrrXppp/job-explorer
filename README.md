# Job explorer

Stateless Python CLI that crawls job sources from HTTP requests in `config.json`, scores each opening against local DOCX resumes with [sentence-transformers](https://www.sbert.net/), and emails a ranked report (new vs previously seen) through the Gmail API.

There is no database or local seen-jobs file. The previous run’s position ids, scores, and resume fingerprints are read from the last three report emails.

See [issue #1](https://github.com/HrrrXppp/job-explorer/issues/1) and the [implementation plan](.cursor/skills/job-explorer/implementation-plan.md).

## Install

Python 3.11+.

```bash
uv sync --extra dev --extra ml
```

`[ml]` installs `sentence-transformers` (needed for a real run). Tests mock the encoder and only need `--extra dev`. Dependencies are locked in `uv.lock`.

The repo includes a working `config.json` (JPMC careers search). Point `resumes[].path` at your DOCX files. Do not commit resumes or `.env`.

## Run

```bash
export GMAIL_CLIENT_ID=...
export GMAIL_CLIENT_SECRET=...
export GMAIL_REFRESH_TOKEN=...
export GMAIL_USER=you@gmail.com
# plus any ${VARS} used in config.json headers

uv run job-explorer --config config.json
```

Create a Gmail OAuth desktop client and store a refresh token in `GMAIL_REFRESH_TOKEN` (scopes `gmail.send` and `gmail.readonly`). The CLI only refreshes that token; it does not run an interactive OAuth helper.

## How a run works

1. Load `config.json` (search sources and resume paths) and secrets from the environment.
2. Fetch the last Gmail report attachment (`job-explorer-state.json`).
3. Hash each resume file (SHA-256) and compare to fingerprints in that email.
4. Execute each source’s **search** request and extract job items with per-source rules.
5. Issue **detail** requests only when needed: new jobs, or resumes that changed. Old jobs with unchanged resumes reuse cached scores (no detail HTTP).
6. Score fetched descriptions against resumes (cosine similarity as a percent).
7. Send one Gmail message: **New positions** then **Previous positions**, each sorted by match percent descending, plus a JSON state attachment for the next run.

## Configuration

| Location | Contents |
|----------|----------|
| `config.json` | `user_agent`, resume paths, source HTTP requests, extract/detail rules, optional model name and `email.to` |
| Environment | Gmail OAuth (`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, `GMAIL_USER`) and any `${VARS}` used in request headers |

### User-Agent (all requests)

Set `user_agent` once. It is sent on every search and detail request (advertise yourself here). Per-source `headers` do not need to repeat it.

```json
"user_agent": "Your Name (you@example.com; https://github.com/you) — open to backend roles"
```

### Matching

- Resumes are `.docx` files on disk.
- Default local model: `sentence-transformers/all-MiniLM-L6-v2`. The first run downloads it into `.models/` next to `config.json`; later runs load that snapshot and do not contact Hugging Face.
- Score is `max(0, cosine) * 100`, one decimal. With several resumes, the sort key is the best score.

## Tests

```bash
uv sync --extra dev
uv run pytest
```

Default CI mocks HTTP and Gmail (no live job sites or mailbox).

## License

[Apache License 2.0](LICENSE)
