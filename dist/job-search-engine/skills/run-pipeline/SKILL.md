---
name: run-pipeline
description: Phase 2 of the job-search-engine lead-gen pipeline — score fetched job candidates against the department rubric and write kept rows to the department's Google Sheet. Use when a scheduled task or the user says "run the jobs pipeline", "запусти пайплайн вакансий", "run phase 2 for profile X", "score today's candidates", or "drain the write queue". Requires a working folder set up by the setup-search-engine skill.
---

<!-- BUILD NOTE: everything below this line is copied verbatim from
     engine/SKILL.md by make_plugin.py — do not edit here. -->

# job-search-engine — Phase 2: score + sheet write (department-agnostic)

You are this pipeline's relevance judge **and** sheet writer for ONE department
profile per run. Phase 1 (fetch) runs on the pipeline owner's machine via Task
Scheduler and produces the profile's `candidates.json` — a pool of candidate
postings that passed only cheap mechanical filters plus the Phase-1 relevance
gate (compiled from the profile; it drops obvious out-of-scope roles at the
source).

**Your job:** resolve the profile, read its candidate pool, score each
candidate 1–5 against the profile's `rubric.md`, then append `score ≥ 2` rows
to the department's Google Sheet.

---

## Step 0 — Resolve the profile

The scheduled prompt names a profile (e.g. `python`) and usually the working
folder. Then:

- `PROFILE_DIR` = `<working folder>/profiles/<profile>/`. If the prompt did
  not name the folder, glob `**/profiles/<profile>/profile.yaml` across
  mounted folders and take the unique hit (two hits → STOP and report the
  ambiguity; never guess between departments).
- Read `PROFILE_DIR/profile.yaml` → `dept`, `id_prefix`, `sheet.spreadsheet_id`,
  `sheet.tab`, `alert_email`, `candidate_cap`.
- Read `PROFILE_DIR/rubric.md` → **the entire scoring rubric for Step 3**
  (score 1–5 definitions, hard/soft negative signals, role-type policy, bias
  instruction). The rubric may extend the `risk_flags` vocabulary of Step 3.
- All paths below are relative to `PROFILE_DIR`:
  - pool: `candidates.json`, `last_run_report.json`
  - state: `state/seen_urls.json`, `state/role_seen.json`,
    `state/write_queue.json`
  - output: `reports/EXECUTION_REPORT_<YYYY-MM-DD>.md`
- OAuth for the sheet write: `PROFILE_DIR/oauth_client.json` +
  `PROFILE_DIR/oauth_token.json`.
- Lead IDs are `{id_prefix}-NNNN` (e.g. `LEAD-0042`, `PY-0007`).

If `profile.yaml` is missing or lacks `sheet.spreadsheet_id` → write an
execution report describing the problem and STOP.

## Step 1 — Locate `candidates.json`

`PROFILE_DIR/candidates.json`; if absent, glob
`**/profiles/<profile>/candidates.json`, then fall back to
`find / -maxdepth 9 -type f -path "*profiles*<profile>*" -name
"candidates.json" 2>/dev/null | head -5`. Log the path (or its absence) in the
report. Then read `candidates.json` and `last_run_report.json` (same folder).

### Candidate schema

```json
{
  "id": "<sha1(link)[:12]>",
  "board": "GoogleJobs|Indeed|LinkedIn",
  "link": "<canonical URL>",
  "title_guess": "<source-extracted title>",
  "company_guess": "<source-extracted company; may be empty>",
  "date_found_iso": "<timestamp>",
  "date_posted_iso": "<timestamp or null>",
  "raw_type": "html|serpapi_json|linkedin_json",
  "raw_content": "<string, ≤30KB>",
  "date_suspect": false
}
```

`raw_content` is a JSON-dumped SerpAPI item, a JSON-dumped Bright Data LinkedIn
record (`linkedin_json`), or cleaned board HTML — each carries title, company,
location, description, salary and remote flags. **Do not fetch anything over the
network** — the Cowork sandbox blocks outbound HTTP and Phase 1 already fetched.

## Step 2 — Gate on freshness / emptiness

- **`candidates.json` not found** after Glob + find → write
  `reports/EXECUTION_REPORT_<YYYY-MM-DD>.md` recording the empty Glob/find, `pwd`,
  and `ls /sessions`, then STOP. Do not run Phase 1 yourself.
- **`candidates.json` is `[]`** → "no new candidates — Phase 1 ran clean" report
  (include `last_run_report.json` counts), then STOP.
- **`last_run_report.json` `run_at` > 2h old** → flag staleness, then STOP.
- **Queue exception:** if `state/write_queue.json` has `pending` entries, skip
  scoring but still run Steps 4–5 to drain the queue, then report.

---

## Step 3 — Score candidates in chunks of 10

**The rubric is `PROFILE_DIR/rubric.md` — apply it exactly.** It defines what
scores 1 through 5 mean for this department, the negative signals and their
`risk_flags`, the role-type policy, and the uncertainty bias. The subsections
below are department-neutral mechanics.

### Required extraction per candidate

- **title** — canonical role title (fall back to `title_guess`).
- **company** — canonical name (fall back to `company_guess`, then `"Unknown"`).
- **location** — hiring **Region** (column F). Format `Country, City` (full
  country first, city if known): `"Germany, Berlin"`, `"United States, Austin"`.
  Country only when city unknown. US states → `"United States"`; England/
  Scotland/Wales → `"United Kingdom"`. Multi-country → join with ` / `. `"Remote"`
  if fully remote with no stated country, `"Unknown"` if absent.
- **remote_type** — `"Remote"` | `"Hybrid"` | `"On-site"` | `"Unknown"`.
- **salary** — raw string (e.g. `"€60k–€80k"`, `"$120,000/yr"`) or `"Not listed"`.
  **Never blank.**
- **risk_flags** — closed vocabulary, `; `-joined, empty if none (scoring/triage
  notes go in `reason`, NOT here). Base vocabulary (the rubric may extend it):
  - `lang:<code>` — requires a non-English language (ISO-639-1, e.g. `lang:de`).
    Do not flag English.
  - `clearance` — security clearance / background / credit check.
  - `citizenship` — specific citizenship / work-authorization / mandatory
    relocation + visa needed.
  - `on-site-strict` — explicitly no-remote / ≥4 office days despite an
    otherwise acceptable region.
  - `geo:<cc>` — remote but restricted to residents of one country
    (`geo:us`, `geo:uk`, `geo:ca`, …).
  - `hybrid-skills` — the role demands a second unrelated specialism on top of
    the core role (see the rubric for this department's definition).
  - `degree` — mandatory formal degree requirement.
  - `date-suspect` — candidate arrived with `"date_suspect": true` (aggregator
    date not trusted).
  - `suspicious` — scam / fake-looking company or domain (job-spam aggregator
    reposts).

### Chunk the work

Process in chunks of **10** (last may be smaller); sleep 1s between chunks. For
each chunk return a JSON array, one object per candidate:

```json
[
  {
    "id": "<candidate id>",
    "score": 1-5,
    "reason": "<one sentence, ≤ 15 words, why this score not another>",
    "extracted": {
      "title": "...", "company": "...", "location": "...",
      "remote_type": "Remote|Hybrid|On-site|Unknown",
      "salary": "...", "risk_flags": "..."
    }
  }
]
```

**Scoring failure handling:** if a chunk isn't parseable JSON, retry once with
"JSON only, no prose". If the retry also fails, default that chunk to score 2,
reason `"scoring failed — defaulted to review"`, fields from `*_guess`. Log it.

---

## Step 3.9 — Persist scored work to the durable write queue

The queue decouples scoring from writing (`candidates.json` is overwritten every
Phase 1 run). File `state/write_queue.json`:

```json
{"entries": [
  {"queued_at": "<ISO>", "candidate_id": "<id>", "link": "<url>",
   "status": "pending|written|dropped",
   "row": { "date_found":"...", "title":"...", "company":"...", "board":"...",
            "location":"...", "remote_type":"...", "salary":"...",
            "risk_flags":"...", "link":"...", "status":"New",
            "date_posted":"...", "score":N, "reason":"..." },
   "lead_id": "<{id_prefix}-NNNN, at write time>", "written_at": "<ISO, at write time>"}
]}
```

The file may also carry optional `_note` / `_archive` top-level keys (rotation
metadata) — always access `entries` by key and preserve unknown top-level keys
when dumping. Dump with ONE entry per line so the file stays tool-readable.

**Rotation (added 2026-07-06):** in the source (uiux) pipeline the journal grew
into a 230 KB single line, exceeded file-tool read limits and silently broke
journaling (sheet writes succeeded; entries had to be backfilled from
execution reports). To prevent recurrence, at the START of Step 3.9: if
`state/write_queue.json` exceeds ~120 KB or ~400 entries, move all
`written`/`dropped` entries older than 7 days into
`state/write_queue_archive_<first-date>_<last-date>.json` (same
`{"entries": [...]}` shape, pretty-printed) and rewrite the active file with
the remainder. Never read or write the journal via the bash `/mnt` mount (it
can serve stale snapshots) — use the file tools on the host paths.

Before any write: (1) load queue (create `{"entries": []}` if absent);
(2) **expire** `pending` entries older than 7 days → `dropped`, note in report;
(3) **enqueue** today's kept candidates (score ≥ 2), skipping links already in
`state/seen_urls.json` or already in the queue (any status); (3.5) **role_seen
gate:** also skip any candidate whose normalized `<company>|<title>` pair
(built from the LLM-**extracted** fields, normalized exactly per Step 4
invariant 3) matches the first two parts of ANY existing key in
`state/role_seen.json` — **ignore the location part when comparing**
(2026-07-02: specialists flagged reposts of one role under different
locations/titles as duplicates). Do not enqueue; count it as
`duplicate_role (Phase 2)` in the report. Rationale: Phase 1's duplicate_role
gate keys on RAW source fields, so a repost with a fresh URL and
differently-formatted location slips through (2026-07-02: confirmed on a live
duplicate that was written and then had to be deleted). Keys in `role_seen.json`
stay three-part `<company>|<title>|<location>` — only the COMPARISON drops
location;
(4) save. Lead IDs are assigned only at write time.

## Step 4 — Filter, sort, write kept rows

1. Write set = all `pending` queue entries (today's + carried over).
2. Sort by `score DESC`, then `date_posted DESC` (None last).
3. **Lead IDs:** read column A, parse the max `{id_prefix}-NNNN` suffix, assign
   sequentially `{id_prefix}-{MAX+1:04d}`, `+2`, … Re-read column A at batch
   start; never reuse a value — including ids of rows later deleted by hand
   (assign from `max(sheet, queue)+1`; the sheet owner may delete weak rows
   manually, so sheet-missing-but-queue-written ids are expected).
4. Build each row (write **A–J and M–P**; never write K, L):

   | Col | Value |
   |---|---|
   | A | `{id_prefix}-NNNN` (sequential) |
   | B | `date_found` from `date_found_iso`, `YYYY-MM-DD HH:MM` |
   | C | `extracted.title` |
   | D | `extracted.company` |
   | E | `board` |
   | F | `extracted.location` (header **Region**, `Country, City`) |
   | G | `extracted.remote_type` |
   | H | `extracted.salary` (never blank — `"Not listed"`) |
   | I | `extracted.risk_flags` |
   | J | `link` |
   | K | **skip — manual `Comment/CV link`** |
   | L | **skip — manual `SM/PM`** |
   | M | `"New"` |
   | N | `date_posted` from `date_posted_iso` as `YYYY-MM-DD`, else `""` |
   | O | `score` (integer 2–5) |
   | P | `reason` |

5. **Write mechanics — Sheets API v4 via a browser JS fetch** (the sandbox is
   firewalled from `*.googleapis.com`, so run the fetch from a `docs.google.com`
   tab in Chrome MCP — confirmed working 2026-06-30):
   - Refresh an access token: POST `https://oauth2.googleapis.com/token` with
     `grant_type=refresh_token` + `client_id`/`client_secret` from
     `PROFILE_DIR/oauth_client.json` (`installed`) + `refresh_token` from
     `PROFILE_DIR/oauth_token.json` (scope `…/auth/spreadsheets`).
   - Locate rows by reading column A first, then `POST …/{spreadsheetId}/values:batchUpdate`
     with `{valueInputOption:"RAW", data:[{range:"<tab>!A<row>", values:[[...]]}, …]}`
     — write A–J in one range and M–P in another (skip K, L). `spreadsheetId`
     and `<tab>` come from `profile.yaml` `sheet.*`.
   - Do all token + API work inside a single JS execution; **return only a
     summary, never the token** (the sandbox blocks cookie/query-string data in
     return values).
   - **Fallback** (only if the refresh token is revoked): Chrome cell-by-cell
     typing — `type("value")` + separate `key("Tab")` per cell, batched via
     `browser_batch`, never embed `\t`, never press Escape between type and Tab.

   Invariants:
   - **Verify every row after writing** (A–P; O integer 2–5; K, L untouched).
     Retry once; skip + log on second failure.
   - **Per verified row, update THREE state files** (save per row, not batched):
     1. add the link to `state/seen_urls.json` by **load → merge → dump as ONE
        array** (read, `json.loads`, append if absent, `json.dump` whole list via
        temp file + `os.replace`). NEVER append-mode, NEVER glue a second `[...]`
        block — that crashes Phase 1's parser.
     2. mark the queue entry `status:"written"` + `lead_id` + `written_at`.
     3. add the role key to `state/role_seen.json`:
        `"<company>|<title>|<location>": "<YYYY-MM-DD>"`, each part lowercased,
        every char outside `[a-z0-9а-яё#+ ]` → space, whitespace collapsed,
        trimmed. Skip if company normalizes to empty or starts with "unknown".
        Must match `_norm_role_part` in `engine/main.py`. **If the key already
        exists, update its date in place — NEVER append a second copy of the
        same key** (duplicate JSON keys silently shadow each other; happened
        2026-07-02). Always load → modify dict → dump whole object (temp file +
        `os.replace`), same as seen_urls.

## Step 4.9 — ALERT on blocked writes

If both write paths fail and there are `pending` entries: send an email via the
connected Gmail tools to the profile's `alert_email`, subject
`[{dept}-pipeline] ALERT: sheet write blocked <YYYY-MM-DD>`, body = cause,
pending count, the one action needed. If only a draft tool exists, create the
draft AND a same-day Google Calendar event `⚠️ {dept}-pipeline: sheet write
blocked` with a popup reminder. Alert on the FIRST blocked run. Note it in the
report.

---

## Step 5 — Output

Write `PROFILE_DIR/reports/EXECUTION_REPORT_<YYYY-MM-DD>.md` with: timestamp +
candidate count + `run_at`; per-source counts and filter hits (`no_link`,
`blocked_domain`, `duplicate`, `duplicate_role`, `excluded`, `too_old`, `capped`
(+ `candidate_cap`), `capped_out_counts`); **score histogram**
`Score 1: N | 2: N | 3: N | 4: N | 5: N`; a per-candidate line
`<id> <board> "<title>" — score <N> — <"written to row X" | "below threshold">`;
chunking diagnostics; sheet-write errors + which path was used; queue state
(written / pending / dropped — non-zero pending after success is a bug, flag it);
whether the Step 4.9 alert fired. Keep the histogram format stable across runs —
it is how the pipeline owner tunes the threshold.

---

## Hard rules

- **No `WebFetch`, no `WebSearch`, no Python fetching.** Phase 1 runs on the
  Windows box; the Cowork sandbox blocks outbound HTTP.
- Chrome MCP is used **only** to talk to Google (Sheets API JS calls or fallback
  typing). Browser JS `fetch` only against `oauth2.googleapis.com` and
  `sheets.googleapis.com`.
- **Never echo access tokens or client secrets** into reports, logs, or tool
  output. Status strings only.
- Never overwrite an existing row — verify the target row is empty first.
- Never put all column values into one cell. Verify each cell after write.
- **Salary (H) never blank** — default `"Not listed"`.
- **Score (O) is an integer 2–5 only** — score-1 candidates never reach the sheet.
- **ID (A) is `{id_prefix}-NNNN` — never reuse a value.** Re-read column A at
  batch start.
- **Columns K and L are manual — never write to them.**
- **When uncertain about a qualifying attribute, score 2 or 3 rather than 1**
  — recall over precision (see the rubric's explicit bias instruction).
