# Job explorer

Python CLI that crawls job sources from HTTP requests in `config.json`, scores each opening against local DOCX resumes with [sentence-transformers](https://www.sbert.net/), and writes a ranked report (new vs previously seen) as HTML and JSON files.

There is no database. The previous run’s position ids, scores, and resume fingerprints are read from the last three JSON reports in `reports/` (or `reports_dir` in config).

See [issue #1](https://github.com/HrrrXppp/job-explorer/issues/1) and the [implementation plan](.cursor/skills/job-explorer/implementation-plan.md).

## Install

Python 3.11+.

```bash
uv sync --extra dev --extra ml
```

`[ml]` installs `sentence-transformers` (needed for a real run). Tests mock the encoder and only need `--extra dev`. Dependencies are locked in `uv.lock`.

The repo includes a working `config.json`. Point `resumes[].path` at your DOCX files. Do not commit resumes, `.env`, or files under `reports/`.

## Run

```bash
uv run job-explorer --config config.json
```

Each run writes a pair of files named with the UTC date and time, for example:

- `reports/job-explorer-2026-09-15T013600Z.html`
- `reports/job-explorer-2026-09-15T013600Z.json`

To seed previous positions (for example the last Gmail `job-explorer-state.json` attachment), copy that file into `reports/` before the first run. A file named `job-explorer-state.json` is read the same way as a dated JSON report.

## How a run works

1. Load `config.json` (search sources and resume paths) and any `${VARS}` from the environment.
2. Read the last three JSON reports in `reports_dir` (newest first) and merge them.
3. Hash each resume file (SHA-256) and compare to fingerprints in that state.
4. Execute each source’s **search** request and extract job items with per-source rules.
5. Issue **detail** requests only when needed: new jobs, or resumes that changed. Old jobs with unchanged resumes reuse cached scores (no detail HTTP).
6. Score fetched descriptions against resumes (cosine similarity as a percent).
7. Write one HTML report and one JSON state file: **New positions** then **Previous positions**, each sorted by match percent descending. Matches at **20% or below** are omitted from the HTML (and visible counts) but stay in the JSON so they remain processed.

## Configuration

| Location | Contents |
|----------|----------|
| `config.json` | `user_agent`, resume paths, source HTTP requests, extract/detail rules, optional model name, `reports_dir` |
| Environment | Any `${VARS}` used in request headers |

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

Default CI mocks HTTP (no live job sites).

## License

[Apache License 2.0](LICENSE)
