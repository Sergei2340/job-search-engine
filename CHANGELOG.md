# Changelog — job-search-engine

Notable changes to the shared engine (`engine/`), profiles, and the plugin
build. Dates are local (Warsaw). Repo created 2026-07-02 by generalizing the
uiux-lead-generation pipeline (see that project's CHANGELOG for prior
history).

## 2026-07-06 — Repo hygiene: ship serpapi test, fix template pointer, backfill history (0.4.2)

Housekeeping pass — no engine behavior change, but the shipped plugin content
changes, so a patch bump:

- **`scripts/make_plugin.py`:** stage `tests/*.py` via glob instead of a
  hardcoded three-file list. `tests/test_serpapi_fetch_returns_list.py` (the
  serpapi `fetch()` regression guard added in 0.3.1) was being silently dropped
  from every build; it now ships, and future tests are picked up automatically.
- **`profiles/_template/profile.yaml`:** removed a dangling pointer to a
  non-existent `docs/ADD_DEPARTMENT.md`; onboarding is the setup-search-engine
  skill.
- **Docs:** root README development section now lists all three offline tests;
  the working-folder README (`assets-extra`) and layout notes match what ships;
  fixed the "cron variant included" wording in the plugin README (no runner file
  ships — cron is a documented alternative).
- Removed the spent one-off `REBUILD_PLUGIN_TASK.md` (its record is the 0.4.1
  entry below) and backfilled the 0.1.0–0.4.0 changelog history.

## 2026-07-06 — Atomic Phase 1 writes + write_queue rotation rule (mirrored from live pipelines)

Mirrored the fixes made today in the live uiux and Unity pipelines so they
survive the future cutover:

- **`engine/main.py`:** new `atomic_write_json()` (temp file + fsync +
  `os.replace`) replaces `write_text` for candidates.json and
  last_run_report.json. Motivation: on 2026-07-06 the uiux Phase 2 found
  candidates.json as two concatenated JSON arrays ("Extra data") — a plain
  `write_text` leaves a window where readers/sync layers can observe a
  partially rewritten file. Verified: py_compile OK, 2 call sites, no
  `write_text` left; `import os` added.
- **`engine/SKILL.md` Step 3.9:** journal rotation rule — at run start, if
  `state/write_queue.json` exceeds ~120 KB or ~400 entries, archive
  `written`/`dropped` entries older than 7 days to
  `state/write_queue_archive_<from>_<to>.json`; dump ONE entry per line;
  optional `_note`/`_archive` top-level keys are legal and must be preserved;
  journal via file tools only (the bash `/mnt` mount can serve stale
  snapshots). Motivation: the uiux journal grew into a single ~230 KB line,
  exceeded file-tool read limits and silently broke journaling on
  2026-07-05..06 (backfilled from execution reports the same day).
- Plugin note: `run-pipeline` merges `engine/SKILL.md` at build time — rebuild
  the plugin (`scripts/make_plugin.py`) to pick up the rotation rule.

## 2026-07-03 — /triage-calibration skill (0.4.0)

Added the triage-calibration skill: decomposes the two-phase triage funnel with
real run numbers, then walks any parameter change (gate, rubric, filters,
blocked domains) through diff → backtest → backup → log → one-command rollback.
Explanation and safe tuning, not repair. (c31c255)

## 2026-07-03 — Repair truncated serpapi_jobs.py (0.3.1)

Restored the lost `return out` in `serpapi_jobs.fetch()` — a manual-upload
truncation made it return `None`, so SerpAPI (the primary volume source)
silently contributed zero postings — and repaired `engine/SKILL.md`. Added
`tests/test_serpapi_fetch_returns_list.py` to guard the regression (the offline
e2e test stubs the whole source, so it never exercised the real fetch body).
(4e799ff)

## 2026-07-02 — Base sources = SerpAPI + LinkedIn (0.3.0)

Removed the WeWorkRemotely and RemoteOK source connectors; the engine's base
sources are SerpAPI (Google Jobs) and LinkedIn via Bright Data. (f5951da)

## 2026-07-02 — research-job-boards skill (0.2.0)

Added the research-job-boards skill (live-verifies candidate boards for a role
and reports an integration path per board) and fixed a CRLF leak in the plugin
build. (6a53741)

## 2026-07-02 — Initial repo (0.1.0)

Extracted the shared engine and Cowork-plugin sources from the
uiux-lead-generation pipeline into a department-agnostic repo, with the built
marketplace layout under `dist/`. (eb0459d)
