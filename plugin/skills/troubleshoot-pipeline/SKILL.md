---
name: troubleshoot-pipeline
description: Diagnose and fix problems with the job-search-engine lead-gen pipeline. Use when the user reports "pipeline didn't run", "пайплайн не отработал", "no new leads today", "LinkedIn returned 0", "sheet write blocked", "duplicates in the sheet", "candidates.json is stale/empty", "SerpAPI returned nothing", or any failed/suspicious daily run of the jobs pipeline.
---

# job-search-engine — troubleshooting

Locate the working folder (glob `**/profiles/*/profile.yaml`; ask which
profile if several). Evidence lives in: `profiles/<dept>/last_run_report.json`
(Phase 1), `profiles/<dept>/logs/fetch_*.log` (Phase 1 runner),
`profiles/<dept>/reports/EXECUTION_REPORT_*.md` (Phase 2),
`profiles/<dept>/state/*` (dedup + queue). Read those FIRST, then match the
symptom below. Never print API keys or OAuth contents while diagnosing.

## No candidates.json / stale `run_at`

Phase 1 didn't run or crashed.
- No fresh `logs/fetch_*.log` at the scheduled hour → Task Scheduler: machine
  off, task disabled, or wrong user. Have the user run
  `Start-ScheduledTask -TaskName "<dept> Jobs Fetch"` and read the new log.
- Log ends non-zero → the log contains the traceback; typical: missing
  requirements (pip step failed — run
  `python -m pip install -r requirements.txt` manually), bad YAML edit in
  profile.yaml (validate: `python -c "import yaml;yaml.safe_load(open('profiles/<dept>/profile.yaml'))"`),
  moved working folder (re-register the task with the new path).

## A source returns 0

Check `source_counts` in `last_run_report.json`.
- **serpapi = 0**: missing/exhausted SERPAPI_KEY (250/month budget — check the
  SerpAPI dashboard; 8 queries/day max), or over-narrow queries. Test one
  query manually on serpapi.com playground.
- **linkedin_brightdata = 0**: (a) already triggered today (UTC) — the
  run-once gate; normal on re-runs, check `state/linkedin_state.json`;
  (b) snapshot poll timeout (log line "not ready after 900s") — rare; if
  chronic, the profile's `inputs` list is too big or Bright Data is slow that
  day; (c) missing key / dataset not subscribed — log says which.

## Candidates fetched but kept ≈ 0

`filter_counts` tells which gate ate them:
- huge `duplicate`/`duplicate_role` right after setup → state was copied from
  another machine or a prior test; expected on re-runs the same day.
- everything filtered at the source (raw counts high, candidates low) → the
  relevance gate is too strict: run the dept gate test, add the missed titles
  as cases, loosen `allow_titles`/`weak_titles`, re-test, re-run.

## Sheet write blocked (Phase 2 report says both paths failed)

- `invalid_grant` → refresh token revoked/expired: re-run
  `python scripts/get_oauth_token.py --profile <dept>` on the host (see the
  setup-search-engine skill's oauth-setup reference), then re-run Phase 2 — the
  write queue kept everything pending, nothing is lost.
- Chrome path errors → extension signed out / wrong Google account in the
  browser profile; verify a docs.google.com tab opens logged-in.
- Confirm the alert fired (email/calendar); if connectors are missing, that's
  a setup gap — offer to add them.

## Duplicates appeared in the sheet

- Same URL twice → `state/seen_urls.json` corrupted or hand-edited: it must be
  ONE JSON array; the engine recovers concatenated arrays automatically but
  report it. Confirm Phase 2 followed the load→merge→dump invariant.
- Same role, different URL/location → the role_seen Phase-2 gate: verify the
  written key exists in `state/role_seen.json` and that comparison ignores
  location (engine/SKILL.md Step 3.9 (3.5)). Delete the duplicate row in the
  sheet by hand; NEVER reuse its id; leave its link in seen_urls.

## Pending queue entries after a successful run

A bug by definition — Step 4 must drain pending on success. Re-run Phase 2
(queue exception path drains without re-scoring); if entries are older than
7 days they expire to `dropped` — check why writes failed on the original day.

## Costs suddenly higher

Bright Data bills per record: check `inputs` count × days, and that
`run_once_per_day: true` is still set. SerpAPI: queries/day × 31 must stay
under the plan.

## Files mysteriously corrupt (NUL bytes, glued JSON)

Known Windows/mount artifact. Fix: read bytes, strip `\x00`, rewrite. The
engine's state loaders already self-heal; if a profile.yaml or test file is
affected, strip and re-run.
