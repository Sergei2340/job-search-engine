---
name: setup-search-engine
description: End-to-end onboarding wizard for the job-search-engine lead-gen pipeline. Use when the user runs /setup-search-engine, says "set up the jobs pipeline", "настрой пайплайн вакансий", "install the lead pipeline for my department", "onboard my department to job search", "configure job-search-engine", or has just installed this plugin and wants to start. Walks through environment checks, department interview, API keys, Google Sheet, profile generation, and a proving end-to-end run.
---

# job-search-engine — department onboarding wizard

Guide the user from a fresh Claude install to a **provably working** daily
lead-gen pipeline for their department. Talk to the user in their language;
keep explanations non-technical unless asked. Do NOT skip the final proving
run — setup is complete only when the DONE criteria at the end are all met.

The pipeline (two phases, per department):
- **Phase 1 (their machine, daily, Task Scheduler):** Python fetches job
  postings from SerpAPI/Google Jobs and LinkedIn (Bright Data); mechanical
  filters + a role-relevance gate produce `candidates.json`.
- **Phase 2 (Cowork scheduled task, ~30 min later):** Claude scores candidates
  1–5 against the department rubric and writes rows to their Google Sheet
  (see the `run-pipeline` skill).

Everything department-specific (queries, gate, rubric, sheet, keys, state)
lives in THEIR working folder — nothing private ships with this plugin.

## Step 0 — Working folder & scaffold

1. Ask the user to select (or create) a folder for the pipeline, e.g.
   `Documents/job-search-engine`. Request access via the directory tool if not
   already mounted.
2. Copy the scaffold from the plugin assets (`<plugin root>/assets/`, i.e. two
   directories up from this SKILL.md, then `assets/`) into the working folder:
   `engine/`, `scripts/`, `profiles/_template/`, `requirements.txt`,
   `.gitignore`, `README.md`. Do not overwrite an existing profile if re-running.
3. Record the engine version from `assets/ENGINE_VERSION` into the working
   folder (used later by plugin updates: newer plugin → offer to re-copy
   `engine/` only, never `profiles/`).

## Step 1 — Environment audit

Run the checks in `references/environment-checks.md`. Summary:

1. **Claude in Chrome extension** — REQUIRED for sheet writes. Verify by
   listing browser tabs via the Chrome tools; if unavailable, send the user to
   install it (claude.ai/chrome) and re-check. Do not proceed to Step 6
   without it.
2. **Python 3.10+ on the host** — the sandbox cannot check the host: give the
   user `python --version` to run in their terminal and confirm the output.
3. **Always-on expectation** — Phase 1 runs at a fixed hour; the machine must
   be on. Confirm this is acceptable or pick a time the machine is reliably on.
4. **Gmail / Google Calendar connectors** (optional, recommended) — used for
   "sheet write blocked" alerts. If absent, alerts degrade to report-only;
   note it and continue.

## Step 2 — Department interview

Use AskUserQuestion (grouped, not one long form). Collect:

1. **Department & prefix**: dept slug (e.g. `python`) and a UNIQUE lead-id
   prefix (e.g. `PY`). Explain: ids look like `PY-0001` in the sheet.
2. **Roles in scope**: exact titles they can staff (e.g. Python Developer,
   Backend Engineer). Any seniority limits (take juniors?).
3. **Adjacent roles OUT of scope**: what looks similar but they cannot answer
   with a CV (e.g. Data Scientist for a Python dept). This seeds the gate's
   deny list.
4. **Markets/geos**: which countries; remote-only or hybrid ok.
5. **Hybrid-skill killers**: which "also must do X" demands kill conversion
   for them (per-domain analog of designer-must-code-frontend).
6. **Alert email** for blocked-write alerts.
7. **Schedule hour**: any other job-search pipelines on this machine or
   shared API keys? If yes, pick a slot a FULL HOUR away from existing ones;
   Phase 2 always +30 min after Phase 1 (LinkedIn snapshots build up to 15 min).

## Step 3 — Keys, sheet, OAuth

Follow `references/services-setup.md` with the user, collecting into
`profiles/<dept>/.env` (create the profile dir from `profiles/_template/`):

1. **SERPAPI_KEY** — their OWN key (per-department budget: 250 req/month ≈ 8
   queries/day max; size the query list accordingly).
2. **BRIGHTDATA_API_KEY** — optional but strongly recommended (LinkedIn is the
   richest source of agency/staff-aug leads). Requires subscribing to the
   "LinkedIn job listings — discover by keyword" dataset. The source
   self-skips if the key is absent.
3. **Google Sheet** — user creates a sheet, pastes the exact A1:P1 header from
   `references/sheet-template.md`, shares the URL; extract `spreadsheet_id`
   into `profile.yaml`. Columns K and L are theirs (manual) — never written.
4. **OAuth for sheet writes** — two paths (see `references/oauth-setup.md`):
   given an `oauth_client.json` by the pipeline owner → save it and run
   `python scripts/get_oauth_token.py --profile <dept>` on the host; or create
   their own Google Cloud OAuth Desktop client first. Verify both
   `oauth_client.json` and `oauth_token.json` exist in the profile dir before
   proceeding. Never read secrets aloud or echo them into chat.

## Step 4 — Generate the profile

1. From the interview, fill `profiles/<dept>/profile.yaml` (start from the
   template): queries for SerpAPI (≤ 8/day), LinkedIn inputs (keyword × geo,
   lean — billed per record), caps, schedule, alert email.
2. **Draft the relevance gate** (`relevance_gate` in profile.yaml):
   deny/disambiguate/allow/weak regex lists from the interview answers. Show
   the user a plain-language summary of what will be dropped vs passed and
   confirm. Recall over precision: deny only what can NEVER be their lead.
3. **Draft `rubric.md`** from `profiles/_template/rubric.md`: business
   context, role-type policy table, their hybrid-skill killers, any vendor
   exclusion. Show the score 1/2/5 definitions for confirmation.
4. **Generate gate tests**: copy `assets/tests/` into the working folder,
   create `tests/test_gate_<dept>.py` with 15–30 cases from the interview
   (in-scope titles, out-of-scope adjacents, ambiguous ones) and run it in the
   sandbox (`python -m tests.test_gate_<dept>`) until green. Also run
   `python -m tests.test_triage_filters` and `python -m tests.test_e2e_offline`.

## Step 5 — Proving run, Phase 1 (their machine)

The sandbox cannot reach job boards — Phase 1 must run on the host:

1. Give the user:
   ```
   cd <working folder>
   python -m pip install -r requirements.txt
   python -m engine.main --profile <dept>
   ```
2. When they say it finished, read `profiles/<dept>/last_run_report.json` and
   `candidates.json` from the working folder. Sanity checks:
   - every enabled source returned > 0 raw postings (LinkedIn may be 0 only on
     re-runs the same UTC day — the run-once gate);
   - `candidate_count` is neither 0 nor suspiciously = cap with one source
     dominating;
   - spot-check 5 candidate titles with the user: do they look like THEIR roles?
3. If kept ≈ 0 → the gate is too strict; if full of noise → too loose. Adjust
   `relevance_gate`, re-run the gate tests, ask the user to re-run Phase 1
   (append `--max-age 48` if the day's volume is thin). Iterate until sane.

## Step 6 — Proving run, Phase 2 (score + write live)

Prove the write path end-to-end NOW, per the `run-pipeline` skill mechanics:

1. Score the fetched candidates against `rubric.md` (chunks of 10).
2. Write the top 1–3 rows (score ≥ 2) to their sheet via the Chrome + Sheets
   API path, verify each cell, update `state/seen_urls.json`,
   `state/role_seen.json`, `state/write_queue.json` exactly per invariants.
3. Show the user the rows in their sheet; confirm columns land correctly and
   ids start at `<PREFIX>-0001`.
4. Write the first `reports/EXECUTION_REPORT_<date>.md`.

## Step 7 — Register the schedules

Per `references/scheduling.md`:

1. **Phase 1**: generate the ready-to-paste PowerShell `Register-ScheduledTask`
   command for their hour and working folder (runner:
   `engine\run_fetch.ps1 -ProfileName <dept>`). Have them run it AND
   `Start-ScheduledTask` once; verify a new log appears in
   `profiles/<dept>/logs/`.
2. **Phase 2**: create the Cowork scheduled task `<dept>-jobs-pipeline`, cron
   `30 <hour> * * *`, prompt: "Run the job-search-engine run-pipeline skill
   for profile `<dept>` in <working folder>." Tell the user to click **Run
   now** once in the Scheduled sidebar to pre-approve Chrome/Gmail tools, and
   that Cowork tasks fire only while the Claude app is open.

## DONE criteria (all must hold — recap to the user)

- Gate tests green; triage + e2e offline tests green.
- Phase 1 ran on the host: report + candidates present and sane.
- ≥ 1 real row written to their sheet, verified, state files updated.
- Task Scheduler job registered and test-fired (log file exists).
- Cowork scheduled task created and pre-approved.
- `.env`, `oauth_*.json` in place; nothing secret echoed to chat.

Close with the calibration note: watch the score histogram in daily reports
for the first week; collect specialist feedback in column K; feed dead/paywall
domains into `state/blocked_domains.json` and conversion-killing patterns back
into the rubric. For problems, point them to the `troubleshoot-pipeline` skill.
