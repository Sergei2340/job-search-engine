# Changelog — job-search-engine

Notable changes to the shared engine (`engine/`), profiles, and the plugin
build. Dates are local (Warsaw). Repo created 2026-07-02 by generalizing the
uiux-lead-generation pipeline (see that project's CHANGELOG for prior
history).

## 2026-07-06 — update-to-latest-version skill + release discipline (0.7.0)

Deployed pipelines roll out from different plugin versions and get customized
between upgrades. This release adds the machinery to upgrade one in place
without losing that customization, and the discipline that keeps future
upgrades safe.

- **New skill `update-to-latest-version`** (`plugin/skills/update-to-latest-version/`):
  fingerprints a deployment (integrity → lineage → engine version by hash-match
  against shipped manifests, not by its self-reported `ENGINE_VERSION`), then
  routes it — already-current / repair-first / fork→transplant / in-place. In
  place it REPLACEs `engine/` wholesale (copy-verify-swap, after verifying the
  deployed engine is intact or surfacing a hand-edit as a fork event) and
  three-way-merges `profile.yaml`/`rubric.md`: deployed file vs the template of
  ITS version vs the new template, per `##`-heading section, proposing each
  change with a plain-language reason and applying only on approval. Rides
  triage-calibration's pending/backup/log/rollback/watch machinery; sheet
  migrations cite the setup skill's canonical procedure. References:
  `migrations.md` (per-release steps: → 0.5.0, → 0.6.0; version-base floor
  mapping) and `transplant.md` (pre-plugin forks like uiux/Unity).
- **Shipped upgrade inputs:** `profiles/_template_history/<version>/` (past
  template snapshots — the 3-way base) and `manifests/<version>.sha256`
  (per-version engine hashes — drift detection). Backfilled for 0.3.0–0.6.0
  from git; the current version's pair is generated/checked at build.
- **`scripts/make_plugin.py`:** stages the history + manifests, generates and
  sync-checks the current version's manifest, adds `.sha256` to the scanned
  text suffixes, and tightens the non-template-profile privacy guard so
  `_template_history/` passes by rule rather than by prefix accident.
- **Release discipline** codified in the root README + a compatibility rule
  (default-off-when-absent, missing-key ≡ neutral, sentinel-guarded contract
  surfaces, additive schemas / lazy state, no lockstep) — generalizing the
  runtime guards 0.6.0 shipped. Enforced by `tests/test_template_history.py`
  (self-skips outside the repo) + the build's manifest-sync check.
- setup Step 0.3 reroutes plugin updates to the new skill and pins the
  `ENGINE_VERSION` artifact; troubleshoot points mixed-version symptoms at it;
  plugin README lists it; the triage parameter-map's 0.5.0 port anchor is
  corrected to the real position.
- No engine, rubric, or sheet change — a deployment already on 0.6.0 sees only
  the new upgrade tooling.

## 2026-07-06 — Company-size enrichment + Headcount sheet column (0.6.0)

Follow-through on 0.5.0: the Company-size rule scored on inference; now Phase 1
fetches the actual number. Two coupled parts — the enrichment data and a new
sheet column that shows it to sales reps directly (11–500 answer far more
often; giants almost never do — reps prioritize without decoding the score).

- **Part A — `engine/` (Phase 1):** after filters + cap, LinkedIn candidates'
  `company_url` values are deduped and resolved via a persistent cache
  (`state/company_size_cache.json`); uncached companies go to the Bright Data
  "LinkedIn companies — collect by URL" dataset (`gd_l1vikfnt1wgvvqz95w`, same
  Datasets v3 trigger/poll as the jobs source, reusing a parameterized
  `_poll_snapshot`). Each candidate gains `company_size`: a normalized bucket
  (`"51-200"`) or `null`. New `engine/company_enrich.py` + `engine/_util.py`
  (atomic_write_json moved there to break the import cycle). Graceful
  degradation: no key / disabled / API error → `null`, pipeline proceeds.
  Billing is at trigger time, so a poll timeout journals the snapshot id
  (`_pending`) and recovers it next run instead of re-billing.
- **New profile knob `enrichment.company_size.*`** (top-level, NOT under
  `sources:`): `enabled` (template default `true`; OFF when the block is
  absent, so refreshing only `engine/` never starts surprise billing),
  `max_per_run` (50), `ttl_days` (180), `negative_ttl_days` (30). Optional
  `COMPANY_SIZE_CACHE_FILE` env override shares one cache across departments
  on a shared Bright Data account.
- **Part B — sheet layout A–Q (was A–P):** new column **E Headcount** between
  Company and Board; everything from Board shifts one right (manual columns now
  L/M, Status N, Date Posted O, Score P, Reason Q). Pipeline writes A–K and
  N–Q. Display rule (`engine/SKILL.md`): enriched bucket verbatim; `≈`-prefixed
  estimate only for a positively recognized giant (e.g. `≈10,001+`); else
  `Unknown` — never blank, mirroring the salary rule. Phase 2 refuses to write
  unless `E1` reads `Headcount` (guards an unmigrated sheet from a one-column
  shift onto the manual columns).
- **`profiles/_template/rubric.md`:** Company-size rule detection step 1 now
  names the `company_size` field as primary evidence; raw_content phrases
  become secondary. Headings and section order preserved.
- **Docs/skills:** sheet-template rewritten (17 columns, A1:Q1, migration note
  that pauses the scheduled task first); setup wizard points at A1:Q1 and the
  companies dataset; triage parameter-map gains the `enrichment.company_size`
  knob block + a "Headcount all Unknown" symptom; troubleshoot gains the same
  symptom + a cost note; every K/L feedback-column mention shifts to L/M.
- **Migration (any pre-0.6.0 sheet):** pause the Phase-2 scheduled task, insert
  one blank column left of Board (new E), title it `Headcount`, update the
  plugin, re-enable — Sheets shifts existing data right automatically; state
  files unaffected. Old pending `write_queue` entries (no `headcount` key)
  write `Unknown`, never crash.
- **Cost:** $1.5/1K company lookups, 5K/month free tier (per Bright Data
  account); the long-term cache means each company is billed roughly once, so
  steady-state cost trends toward zero.

## 2026-07-06 — Company-size preference in scoring (0.5.0)

Innowise sales feedback: companies with 11–500 employees answer outreach far
more often (sweet spot 50–200 — the ideal customer profile); giant companies
almost never answer. The current rubric contradicted this (Score 4 rewarded
"well-known company"). No new data source or code — the change is entirely
in the scoring rubric template, since Phase 2 already sees the full raw
posting payload and cannot make network calls.

- **`profiles/_template/rubric.md`:** new `## Company-size rule` section
  (detection order: explicit size evidence in `raw_content` → LLM's own
  knowledge of the company name → unknown/ambiguous defaults to neutral,
  never penalized); `## Score 4` reworked so company-size fit (~11–500,
  ideally 50–200) is the primary positive signal, "well-known company" is
  removed, "well-funded" narrowed to "recently funded (seed–C)" to stop it
  re-admitting giants; giant employer (household-name brand or roughly
  5,000+ employees) added as a **soft** negative (−1, floor 2, does NOT
  count toward the two-hard-negatives score-1 rule) flagged `company:giant`
  in `risk_flags` — soft, not hard, because size judgment rests on LLM world
  knowledge and can misfire, and score-1 drops are invisible and
  unrecoverable while a soft −1 still surfaces the row for human review.
- **`engine/SKILL.md`:** added `company:giant` to the base `risk_flags`
  vocabulary (Step 3) — department-agnostic sales signal, not a per-rubric
  extension.
- **`plugin/skills/triage-calibration/references/parameter-map.md`:** new
  symptom row ("гиганты в таблице") and a Phase-2 lever entry describing how
  to port the section into a pre-0.5.0 department rubric as one change.
- **Expected histogram shift:** some existing 4s ("well-known company") drop
  to 3; giants drop one band (e.g. 3 → 2). This is a **template-only**
  change — a live department applies it via the triage-calibration skill
  with a backtest, not automatically.
- **Migration:** rubric-only, one lever (insert `## Company-size rule` between
  `## DACH language rule` and `## Score 2`, rework Score 4, extend the
  soft-negatives line). Since 0.7.0 the `update-to-latest-version` skill walks
  it as its → 0.5.0 step — proposed diffs requiring approval, never a silent
  apply; see that skill's `references/migrations.md`.

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
