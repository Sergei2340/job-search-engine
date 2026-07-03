# job-search-engine — job-posting lead generation for any Innowise department

A daily pipeline: collects fresh job postings, scores them against the
department's rubric, and writes leads to the department's Google Sheet. The
logic (sources, filters, dedup, sheet writes) is shared and lives in `engine/`.

This repository holds the engine and Cowork-plugin sources, with no production
data: each department's instance (profile, secrets, state) lives in its own
working folder, scaffolded by the plugin's setup wizard.

## Architecture (two phases, per department)

**Phase 1 — `engine/main.py` (Python, Windows Task Scheduler, once a day).**
Reads `profiles/<dept>/profile.yaml`, pulls the enabled sources in parallel
(SerpAPI/Google Jobs, LinkedIn via Bright Data),
runs every posting through the profile's relevance gate, applies mechanical
filters (direct link, blocked domains, URL dedup, role dedup, freshness,
fair cap) and writes `profiles/<dept>/candidates.json`. Writes nothing to the
sheet.

**Phase 2 — Claude in Cowork (`engine/SKILL.md`).** The department's scheduled
task names the profile; the SKILL reads `profile.yaml` (sheet, id prefix) and
`rubric.md` (this department's 1–5 scoring rules), scores the candidates and
writes `score ≥ 2` rows to the department's Google Sheet. State invariants
(seen_urls, role_seen, write_queue) live in the SKILL.

## Layout

```
engine/                 shared logic — the only place code lives
  main.py               Phase 1 orchestration (filters, cap, report)
  profile.py            profile.yaml loading/validation + engine defaults
  relevance.py          config-driven gate (deny/disambiguate/allow/weak)
  sources/              source connectors (mechanics; knobs live in the profile)
  SKILL.md              Phase 2 (scoring + sheet write)
  run_fetch.ps1         Task Scheduler runner: -ProfileName <dept>
profiles/_template/     department profile template (ships in the plugin)
scripts/                get_oauth_token.py (sheet OAuth), make_plugin.py (plugin build)
plugin/                 Cowork plugin sources (skills, manifest, working-folder README)
tests/                  filters + offline e2e (ship in the plugin)
```

The department working-folder structure (a copy of `engine/` plus
`profiles/<dept>/` with config, secrets and state) is described in
`plugin/assets-extra/README.md`.

## Development

```powershell
cd job-search-engine
python -m pip install -r requirements.txt
python -m tests.test_triage_filters             # filters
python -m tests.test_e2e_offline                # e2e, no network
python scripts\make_plugin.py                   # builds job-search-engine.plugin
```

Manual Phase 1 runs happen in the department's working folder:
`python -m engine.main --profile <dept>`.

## Invariants (do not break)

- One scheduled task = one profile = one sheet + one state dir. No state is
  shared between departments — overlapping roles (Fullstack↔Node↔Python)
  would produce false dedups.
- `id_prefix` is unique per department; ids are never reused (including after
  manual row deletion — take `max(sheet, queue)+1`).
- Every department has its OWN `SERPAPI_KEY` (a 250 req/month budget ≈ 8
  queries/day). `BRIGHTDATA_API_KEY` and the Google account are shared → the
  departments' schedules are staggered a full hour apart (07:00, 08:00,
  09:00, …).
- `_norm_role_part` in `engine/main.py` and invariants rule #3 of Step 4 in
  `engine/SKILL.md` must match byte-for-byte in semantics.
- Logic changes go only to `engine/`; department-scope changes go only to its
  `profiles/<dept>/`.
