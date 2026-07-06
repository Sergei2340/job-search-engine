# Changelog — job-search-engine

Notable changes to the shared engine (`engine/`), profiles, and the plugin
build. Dates are local (Warsaw). Repo created 2026-07-02 by generalizing the
uiux-lead-generation pipeline (see that project's CHANGELOG for prior
history).

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
