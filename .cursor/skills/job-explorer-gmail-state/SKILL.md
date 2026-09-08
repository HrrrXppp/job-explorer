---
name: job-explorer-gmail-state
description: >-
  Gmail API send/receive for job-explorer: OAuth refresh-token env vars,
  HTML report (new vs previous, sorted by match percent), and stateless
  previous-position state stored in the last three emails. Use when changing email
  format, Gmail client, MIME state, or related pytest.
---

# Gmail report and email state

The process stores **no local run history**. Previous positions, scores, and
resume fingerprints are read from the **last three job-explorer emails** in the
same mailbox (newest first).

## Auth (env only)

| Variable | Meaning |
|----------|---------|
| `GMAIL_CLIENT_ID` | OAuth client id |
| `GMAIL_CLIENT_SECRET` | OAuth client secret |
| `GMAIL_REFRESH_TOKEN` | User refresh token |
| `GMAIL_USER` | Mailbox address |

Scopes: `https://www.googleapis.com/auth/gmail.send` and
`https://www.googleapis.com/auth/gmail.readonly`.

Use `google-auth` + `google-api-python-client`. Refresh access tokens in
memory; do not write token files into the repo. Do not add an interactive
OAuth helper that prints the refresh token.

`config.json` may set `email.to` (list). Default to `GMAIL_USER`.

## Fetch previous state

1. `users.messages.list` with
   `q='subject:"[job-explorer]" filename:job-explorer-state.json'`
   `maxResults=3`, `userId=me`.
2. If zero messages: previous set is empty (all positions are **new**).
3. For each listed message, `users.messages.get` `format=full`; find MIME part
   `filename=job-explorer-state.json` (or `Content-Disposition` filename).
   If `body.data` is missing, download with `messages.attachments.get`
   using `body.attachmentId` (Gmail omits inline data for larger parts).
   Base64url-decode JSON (**version 2**). Skip a message that is corrupt or
   missing the attachment (log a warning; treat that message as empty).
4. Merge newest-first: fingerprints from the newest email that has them;
   cached `positions` newest-wins per id; `position_ids` is the union.

Decoded JSON (**version 2**):

```json
{
  "version": 2,
  "resume_fingerprints": {
    "primary": "sha256:ab…"
  },
  "positions": [
    {
      "id": "example:123",
      "title": "Backend engineer",
      "url": "https://example.com/jobs/123",
      "source_id": "example",
      "scores": {"primary": 87.5}
    }
  ]
}
```

`resume_fingerprints`: SHA-256 hex of each resume file’s bytes, keyed by
resume `id`. Used to decide if resumes are unchanged.

Ignore unknown fields. Corrupt/missing JSON → log warning, treat as empty
previous set (still send this run's email). Legacy `version: 1` with only
`position_ids` is accepted: classify new vs previous, but treat resumes as
**changed** (no skip of detail requests).

## Send report

Multipart:

1. **text/html** — human report.
2. **application/json** attachment `job-explorer-state.json` — **this run's**
   fingerprints plus every position still seen this run (new rows from matching;
   previous rows reused from cache when detail was skipped).

Subject: `[job-explorer] {n_new} new, {n_prev} previous · {date UTC}`

### HTML sections (required)

1. **New positions** — ids not in the merged last-three-email state.
2. **Previous positions** — ids present in that merged state.

Each section sorted by best match percent descending. Each row:

- match % (one decimal)
- title (link to job url if present)
- source id
- best resume id
- optional one-line snippet of description (omit when detail was skipped)

If a section is empty, still render the heading and "None".

Do not omit the JSON attachment even when there are zero positions (empty
`positions` and current `resume_fingerprints`).

## Libraries

Build RFC 2822 with `email.message.EmailMessage`, then
`users.messages.send` with base64url raw.

## Tests

- Encode/decode state JSON (v2 fingerprints + positions; v1 `position_ids`).
- Classification: new vs previous given a previous id set.
- `resumes_unchanged(current, previous)` true only on exact id→hash match.
- HTML contains both section headings and order by percent.
- Gmail client unit tests mock `googleapiclient.discovery.build`; do not call
  Google in CI.
- First-run (no messages) → all new; no skip.
- Malformed attachment → empty previous, no crash.
- Last three emails: union of position ids; newest fingerprints and cached row win.
