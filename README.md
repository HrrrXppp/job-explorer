# Job explorer

Stateless Python CLI that crawls job sources from HTTP requests in `config.json`, scores each opening against local DOCX resumes with [sentence-transformers](https://www.sbert.net/), and emails a ranked report (new vs previously seen) through the Gmail API.

There is no database or local seen-jobs file. The previous run’s position ids, scores, and resume fingerprints are read from the last report email.

## Status

The product design for [issue #1](https://github.com/HrrrXppp/job-explorer/issues/1) is in [`.cursor/skills/job-explorer/implementation-plan.md`](.cursor/skills/job-explorer/implementation-plan.md). The CLI package is not in the tree yet.

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
| `config.json` | Resume paths, source HTTP requests, extract/detail rules, optional model name and `email.to` |
| Environment | Gmail OAuth (`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, `GMAIL_USER`) and any `${VARS}` used in request headers |

Commit an example config only. Do not put API tokens or OAuth secrets in git.

## Matching

- Resumes are `.docx` files on disk.
- Default local model: `sentence-transformers/all-MiniLM-L6-v2`.
- Score is `max(0, cosine) * 100`, one decimal. With several resumes, the sort key is the best score.

## Tests

Behavior is covered with **pytest**. Default CI should mock HTTP and Gmail (no live job sites or mailbox).

## License

[Apache License 2.0](LICENSE)
