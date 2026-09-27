---
name: job-explorer-gmail-state
description: >-
  HTML report (new vs previous, sorted by match percent) and previous-position
  state stored as dated JSON files in reports_dir. Use when changing report
  format, local report files, MIME helpers, or related pytest.
---

# Report files and previous-position state

Each run writes HTML and JSON under `config.json` `reports_dir` (default
`reports/` next to the config). Filenames use UTC date and time:

`job-explorer-YYYY-MM-DDTHHMMSSZ.html`
`job-explorer-YYYY-MM-DDTHHMMSSZ.json`

Previous positions, scores, and resume fingerprints are read from the **last
three JSON files** in that folder (newest first). A seed file named
`job-explorer-state.json` (the old Gmail attachment name) is included. The CLI
does not send Gmail.

## Fetch previous state

1. List `*.json` in `reports_dir`. Sort newest first (UTC stamp in the filename
   when present, otherwise file mtime).
2. Take at most three files. If zero files: previous set is empty (all
   positions are **new**).
3. Decode each as JSON (**version 2**). Skip a file that is corrupt (log a
   warning; treat that file as empty).
4. Merge newest-first: fingerprints from the newest JSON that has them;
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
previous set (still write this run's files). Legacy `version: 1` with only
`position_ids` is accepted: classify new vs previous, but treat resumes as
**changed** (no skip of detail requests).

## Write report

Always write both files for this run, even when there are zero positions
(empty `positions` and current `resume_fingerprints`):

1. **HTML** — human report (`render_html`).
2. **JSON** — fingerprints plus every position still seen this run (new rows
   from matching; previous rows reused from cache when detail was skipped).

### HTML sections (required)

1. **New positions** — ids not in the merged last-three-JSON state.
2. **Previous positions** — ids present in that merged state.

Each section sorted by best match percent descending. Positions whose **best**
match is **20.0% or lower** are omitted from the HTML but **remain in the JSON
file** so the next run still treats them as processed. Each visible row:

- match % (one decimal)
- title (link to job url if present)
- source id
- best resume id
- optional one-line snippet of description (omit when detail was skipped)

If a section is empty (including when every row was ≤ 20%), still render the
heading and "None".

## Tests

- Encode/decode state JSON (v2 fingerprints + positions; v1 `position_ids`).
- Classification: new vs previous given a previous id set.
- `resumes_unchanged(current, previous)` true only on exact id→hash match.
- HTML contains both section headings and order by percent.
- HTML omits best match ≤ 20%; the JSON file still lists those ids.
- Dated filenames; seed `job-explorer-state.json`; last three JSON files merge
  newest-first; malformed JSON → empty previous, no crash.
- First-run (no JSON files) → all new; no skip.
