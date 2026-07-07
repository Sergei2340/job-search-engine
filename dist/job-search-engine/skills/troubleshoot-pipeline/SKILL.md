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

This skill fixes a **broken or failed** run. For chronic tuning of a *working*
pipeline — decomposing how the sorting works, loosening/tightening the gate,
adjusting the rubric or filters, "мало лидов" / "много мусора" as an ongoing
complaint rather than a sudden drop — use the `triage-calibration` skill. If the
trouble started **right after a plugin update** (mixed-version state — e.g. a
newer `engine/` against an un-migrated profile or sheet), the deployment was
likely upgraded incompletely: run the `update-to-latest-version` skill, whose U0
fingerprint reports exactly which surfaces are behind.

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
  relevance gate is too strict. If this is a sudden regression right after a
  profile edit, revert the edit; otherwise it is a chronic-tuning job — hand off
  to the `triage-calibration` skill (it loosens `allow_titles`/`weak_titles`
  with a gate-test + backtest + rollback safety net).

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

## Headcount column (E) all "Unknown"

Enrichment is Phase 1 only — Phase 2 just displays `company_size`. Check in
order:
- No `BRIGHTDATA_API_KEY` in `profiles/<dept>/.env` → enrichment self-skips.
  Expected degradation, not a fault; add the key to enable it.
- `enrichment.company_size.enabled: false` in profile.yaml → deliberately off
  (a calibration decision — see the triage-calibration skill). Note it also
  defaults OFF when the whole `enrichment:` block is absent (e.g. a pre-0.6.0
  profile whose `engine/` was updated but profile.yaml wasn't).
- Enabled + keyed but still Unknown → `logs/fetch_*.log`: trigger/poll errors
  on the companies dataset (`gd_l1vikfnt1wgvvqz95w` — subscription missing?);
  or `company_enrichment.failed` in `last_run_report.json`. Candidates still
  flow with `company_size: null` by design — the pipeline never blocks on
  enrichment.
- `state/company_size_cache.json` corrupt (NUL bytes, glued JSON) → same
  self-heal fix as below; worst case delete it — the only cost is re-lookups
  ($1.5/1K, 5K/month free).
- `≈`-prefixed values (e.g. `≈10,001+`) are NOT enrichment output — they are
  Phase-2 estimates for recognized giants and are normal.
- A one-off `Unknown` on an otherwise-enriched day: pre-0.6.0 pending
  write_queue entries legitimately write `Unknown` once (no headcount key).
- Sheet still on the old A–P layout → Phase 2 refuses to write (E1 precheck).
  Migrate the sheet per the setup skill's `sheet-template.md` first.

## Pending queue entries after a successful run

A bug by definition — Step 4 must drain pending on success. Re-run Phase 2
(queue exception path drains without re-scoring); if entries are older than
7 days they expire to `dropped` — check why writes failed on the original day.

## Costs suddenly higher

Bright Data bills per record: check `inputs` count × days, and that
`run_once_per_day: true` is still set. Company-size enrichment bills only
UNCACHED lookups ($1.5/1K, 5K/month free) — a spike there means the cache
(`state/company_size_cache.json`) was deleted/bypassed, or several departments
share one Bright Data account (the free tier and key are per-account; point
them at a shared `COMPANY_SIZE_CACHE_FILE` to stop paying per department).
SerpAPI: queries/day × 31 must stay under the plan.

## Files mysteriously corrupt (NUL bytes, glued JSON)

Known Windows/mount artifact. Fix: read bytes, strip `\x00`, rewrite. The
engine's state loaders already self-heal; if a profile.yaml or test file is
affected, strip and re-run.
