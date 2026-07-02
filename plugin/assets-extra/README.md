# job-search-engine — working folder

Scaffolded by the `job-search-engine` Cowork plugin's setup wizard. This
folder is the single home of YOUR department's pipeline instance.

```
engine/                 shared pipeline code (updated by plugin upgrades — do not edit)
  main.py               Phase 1: fetch + mechanical filters -> candidates.json
  SKILL.md              Phase 2 contract (scoring + sheet write, run by Claude)
  run_fetch.ps1         Task Scheduler runner: -ProfileName <dept>
scripts/get_oauth_token.py   one-time refresh-token mint for sheet writes
profiles/<dept>/        YOUR department (created by the wizard)
  profile.yaml          queries, relevance gate, sheet id, caps, schedule
  rubric.md             scoring rubric Claude applies in Phase 2
  .env                  SERPAPI_KEY / BRIGHTDATA_API_KEY / SHEET_URL  (secret)
  oauth_*.json          sheet write auth                              (secret)
  state/                dedup + write-queue state (do not hand-edit)
  candidates.json       latest fetch output (overwritten daily)
  reports/, logs/       Phase 2 reports, Phase 1 logs
tests/                  offline tests: gate parity, filters, e2e
```

Daily flow: Task Scheduler `HH:00` → `engine/run_fetch.ps1 -ProfileName <dept>`
→ `candidates.json` → Cowork task `<dept>-jobs-pipeline` `HH:30` → rows in your
Google Sheet + `reports/EXECUTION_REPORT_<date>.md`.

Manual run: `python -m engine.main --profile <dept>` · Tests:
`python -m tests.test_gate_<dept>` / `test_triage_filters` / `test_e2e_offline`.

Rules that keep the data sane: never reuse a lead id; never write sheet
columns K/L (specialists' feedback lives there); state files are whole-file
JSON rewrites, never appends; one profile = one sheet = one state dir.

Problems? Ask Claude to run the plugin's `troubleshoot-pipeline` skill.
