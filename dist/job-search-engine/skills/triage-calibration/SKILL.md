---
name: triage-calibration
description: Explain and safely tune how the job-search-engine pipeline sorts fetched vacancies. Decompose the two-phase triage (profile.yaml fetch gate/filters + rubric.md scoring) using the department's real run numbers, then diff, backtest, apply, log, and roll back parameter changes. Use when the user says "how does the vacancy sorting work", "как работает отбор вакансий", "too few leads" / "too much junk", "слишком мало лидов", "много мусора в таблице", "why was this vacancy dropped", "почему вакансия не попала в таблицу", "calibrate the pipeline", "настрой фильтры", "ослабь / ужесточи гейт", "tune the rubric", "настрой рубрику", "add a blocked domain", "исключи компанию", "rollback the last settings change", "откати изменение настроек". Chronic tuning and explanation only — for a broken or failed run use the troubleshoot-pipeline skill; to add a new job board use research-job-boards. Requires a working folder set up by the setup-search-engine skill.
---

# job-search-engine — triage calibration

Turn the two-phase vacancy triage from a black box into a funnel the department
head can see, then change its parameters **safely**: every edit is previewed as
a diff, backtested against recent real vacancies, backed up, logged, and
reversible with one command. Talk to the user in their language (usually
Russian); keep explanations non-technical unless asked.

Two phases decide which vacancies reach the sheet:
- **Phase 1 (fetch, `engine/`, their machine):** per-source relevance gate +
  six mechanical filters + per-board cap → `candidates.json`. Configured by
  `profile.yaml`. **Gate drops are invisible in the report** — only
  `logs/fetch_*.log` (`raw=N kept=M`) shows them.
- **Phase 2 (score, `run-pipeline` skill):** the model scores each candidate
  1–5 against `rubric.md`; `score ≥ 2` is written to the sheet. Configured by
  `rubric.md`.

**Scope — own the chronic tuning loop, hand off the rest:**
- Acute failure (kept ≈ 0 after a change, a source at 0, sheet write blocked,
  stale/missing `candidates.json`) → **troubleshoot-pipeline**.
- Add / replace a job board → **research-job-boards**.
- First-time setup → **setup-search-engine**.
- Edits ONLY `profile.yaml`, `rubric.md`, `state/blocked_domains.json` in the
  department's working folder. NEVER edit `engine/` code, `dist/`, schedules,
  sheet columns K/L, or `state/seen_urls.json` / `state/role_seen.json`.

Change **one lever per session** by default — otherwise the post-change
histogram is unattributable. When either phase would satisfy the intent, prefer
tuning `rubric.md` (Phase 2) over the gate (Phase 1): gate drops are invisible
and irreversible.

## Step 0 — Locate and fingerprint the deployment

1. Glob `**/profiles/*/profile.yaml` (working folders live OUTSIDE this plugin
   repo). Ignore `_template`. Several profiles → STOP and ask which department;
   never guess. Refuse to operate on the repo's own `profiles/` or on `dist/`.
2. Read `assets/ENGINE_VERSION` (or the working folder's copy). If the layout
   diverges from what this skill documents (no `engine/relevance.py`, config in
   a bare `.env` with no `profile.yaml`, etc. — older forks), **degrade to
   explain-only mode**: decompose the funnel, do not edit.
3. Integrity check `profile.yaml`, `rubric.md`, and `tests/test_gate_<dept>.py`
   against the known corruption class (NUL bytes, truncated tail). A truncated
   rubric produces confidently wrong decompositions — do not proceed on a
   corrupt file; strip + report first.
4. Never print `.env` or `oauth_*.json` contents.

## Step 1 — Decompose: render the funnel with real numbers

Read the LIVE `profile.yaml`, `rubric.md`, `last_run_report.json`, and the last
few `reports/EXECUTION_REPORT_*.md`. Explain **in chat** (offer to save to
`profiles/<dept>/calibration/TRIAGE_MAP_<date>.md`). For each stage give: the
rule in plain language, the current setting with its exact `file:key`, and
yesterday's real count. Honesty rule: stages with no instrumentation
(gate drops, SerpAPI all-hosts-excluded drops, silent zero-sources) are marked
**«нет данных»** — never invent a number. Example fragment:

```
## Воронка отбора вакансий — 3d (2026-07-03)
Вчера: источники дали 137 → в candidates.json 58 → в таблицу 9 (score ≥ 2).

1. Источники — сколько мы вообще видим
   - SerpAPI: 6 запросов из 8/день (profile.yaml → sources.serpapi.queries),
     свежесть date_posted_chip: "date_posted:3days". Вчера после гейта: 91.
   - LinkedIn (Bright Data): 3 связки inputs, окно time_range "Past 24 hours" —
     ЕДИНСТВЕННЫЙ регулятор объёма и стоимости LinkedIn. Вчера: 46.
   ⚠ сколько гейт отбросил по названию — НЕТ ДАННЫХ в отчёте (только logs/).

2. Гейт по названию (relevance_gate) — порядок жёсткий, первый совпавший решает:
   deny → disambiguate → allow → weak → отказ по умолчанию.
   - deny_titles 'graphic designer' → сразу мимо, ДАЖЕ если в описании есть 3D
     (deny сильнее allow).
   - weak_titles 'Artist' проходит только если рядом 'Blender|Maya|3ds'.

3. Механические фильтры (вчера: duplicate 41, duplicate_role 12, too_old 9,
   no_link 3, blocked_domain 2, excluded 0)
   - too_old: старше max_age_hours: 24. Вакансии БЕЗ даты проходят всегда.
   - duplicate_role: та же компания + название за role_seen_window_days: 30;
     город НЕ учитывается, Senior/Junior — разные роли.

4. Потолок candidate_cap: 100 за прогон, поровну между досками.

5. Оценка 1–5 по rubric.md (Phase 2, решает Claude): 1 → не в таблицу; каждый
   жёсткий минус −1 (пол 2); два минуса = 1; порог записи score ≥ 2.
   Гистограмма за неделю: Score 1: 18 | 2: 21 | 3: 9 | 4: 4 | 5: 1
```

Full stage-by-stage catalog with couplings: `references/parameter-map.md`.

## Step 1b — Trace one vacancy (free, read-only)

For "why was THIS vacancy dropped / not in the sheet", replay it offline:
`load_profile("profiles/<dept>")` from the deployment's own `engine/` compiles
the gate into `prof.gate`; call `prof.gate.classify(title, body)` — it returns
`Verdict.reason`, the reason production discards (sources call `is_relevant()`).
Then check the
mechanical filters for that one posting: `state/seen_urls.json`,
`state/role_seen.json` (compare `<company>|<title>`, ignore location),
`state/blocked_domains.json`, `max_age_hours`. Report the first stage that
would drop it. State files are opened READ-ONLY.

## Step 2 — Elicit intent, map it to a parameter

The user states a goal ("больше лидов из Германии", "убрать он-сайт мусор",
"перестать видеть повторы одной вакансии"). Using `references/parameter-map.md`,
propose the matching lever(s) and state the blast radius and couplings BEFORE
drafting (grouped AskUserQuestion, not a re-run of setup's interview). Key
couplings and foot-guns to name aloud:

- `max_age_hours` is capped by `date_posted_chip` (SerpAPI) and `time_range`
  (LinkedIn) — raising it alone changes nothing.
- `filters.extra_unreliable_date_domains` rescues postings from `too_old` BUT
  adds a `-1` date-suspect hard negative at scoring — not a pure recall knob.
- `filters.extra_serpapi_excluded_hosts` is **substring** matching — a short
  token like `jobs` silently kills nearly everything.
- `filters.extra_title_noise_tokens` redefines role identity in BOTH phases
  against historical `state/role_seen.json` keys — must NEVER contain seniority
  words (test-pinned) or dedup breaks.
- An empty `relevance_gate` raises `GateConfigError` and bricks Phase 1.

Flat refusals, with the alternative: the `score ≥ 2` keep threshold (hardcoded
in `engine/SKILL.md` — an engineering change, redirect to rubric-band tuning),
`run_once_per_day`, `engine/` code, schedules (the YAML is informational; real
triggers are Task Scheduler + Cowork), sheet columns K/L. Column-K feedback
routes here: dead/paywall domains → `state/blocked_domains.json`;
conversion-killer patterns → `rubric.md` hard/soft negatives.

## Step 3 — Draft the change as a diff

Copy the target file to `profiles/<dept>/calibration/pending/`, edit THERE, and
show a unified diff against the live file **with a plain-language translation of
every changed line** (never a bare regex diff to a mixed-technical audience).
Re-diff against the live file immediately before Step 7 and abort if it changed
under you (concurrent hand-edit). Rubric edits change values inside sections
only — preserve every heading verbatim (so fixes port across departments).
Vendor exclusion must touch BOTH `filters.excluded_companies` AND the rubric's
vendor-exclusion text, or the two phases desync.

## Step 4 — Static safety: dry-run compile + gate tests

- Compile the drafted `profile.yaml` through the deployment's own
  `engine.profile.load_profile()` (never the repo copy) — catches
  `GateConfigError`, bad regexes, missing required keys, without fetching.
- Lint: refuse `extra_serpapi_excluded_hosts` tokens shorter than ~6 chars or
  common words; refuse seniority words in `extra_title_noise_tokens`; refuse an
  empty gate; verify regexes are single-quoted YAML.
- Gate changed → FIRST add cases to `tests/test_gate_<dept>.py` from the user's
  motivating vacancies, THEN run `python -m tests.test_gate_<dept>`,
  `python -m tests.test_triage_filters`, `python -m tests.test_e2e_offline`
  until green (same discipline as setup Step 4 and troubleshoot).

## Step 5 — Backtest on recent real data

Replay the change offline per `references/safe-change.md`: `gate.classify()` +
the `apply_filters` logic over a corpus (today's `candidates.json` plus any
`profiles/<dept>/calibration/corpus/candidates_*.json` the skill archived, kept
14 days), state files READ-ONLY. Output a per-vacancy delta: KEPT→KEPT,
KEPT→DROPPED (with stage + reason), DROPPED→KEPT, plus per-stage count deltas.
For `rubric.md`: re-score a 10–20 vacancy sample old vs new and show both
histograms in the frozen `Score 1: N | 2: N | …` format.

**Confidence, stated honestly:** gate/filter TIGHTENING and rubric changes
backtest well. Gate LOOSENING cannot — postings the old gate dropped were never
persisted anywhere. Offer an optional live A/B fetch ONLY with explicit consent
and the guard rails in `references/safe-change.md` (`SEEN_URLS_FILE` redirected
to a scratch copy, `--out` to scratch, `linkedin_brightdata.enabled: false` in
the test copy, ≤ 2 of the 8/day SerpAPI budget) — and only after confirming the
day's scheduled run already ran (a dry run before it burns budget AND marks
LinkedIn done for the UTC day, zeroing the evening production run).

## Step 6 — Decision packet + explicit confirmation

One packet: the diff, the backtest delta table, cost impact (SerpAPI queries/day
vs the 8/day cap; LinkedIn `inputs × time_range` per-record billing), and an
invariant checklist (recall-over-precision bias intact in gate and rubric;
hard-negative floor-2 arithmetic untouched; rubric heading structure intact;
role_seen normalization untouched). Ask apply / adjust / abandon via
AskUserQuestion. NEVER apply without showing the packet, even on "просто сделай".

## Step 7 — Backup, atomic apply, calibration log

Back up the live file to
`profiles/<dept>/calibration/backups/<file>.<UTC-timestamp>.bak`. Apply by
replacing the live file with the vetted `pending/` copy (temp file + replace,
LF endings), then verify integrity: no NUL bytes, expected tail present
(`profile.yaml` last key; `rubric.md` ends with the bias section). Append to
`profiles/<dept>/calibration/CALIBRATION_LOG.md` (append-only): UTC timestamp,
intent in the user's own words, files touched, diff summary, backtest numbers,
baseline metrics (last `filter_counts` + last histogram line), expected effect,
and the exact rollback command. Template in `references/safe-change.md`.

## Step 8 — One-command rollback

End every apply by printing the rollback command (PowerShell `Copy-Item` from
the `.bak`). On "откати" / "rollback": read the tail of `CALIBRATION_LOG.md`,
restore the referenced backup, re-run Step 4 (dry-run compile + gate tests) to
prove the restored state is healthy, and append a ROLLBACK entry. If the rolled
change had added cases to `tests/test_gate_<dept>.py`, revert or re-run them too
— restoring the `.bak` alone desyncs tests from the profile. State what rollback
does NOT undo: `seen_urls`/`role_seen` entries, sheet rows, and vacancies
already dropped under the bad config are not resurrected.

## Step 9 — Post-change watch

Ask the user to re-invoke after 1–3 daily runs. On re-invocation with an open
watch in the log: compare the new `source_counts` / `filter_counts` /
`candidate_count` / `capped` and the new histogram line against the baseline in
the log entry. Declare **CONFIRMED** (moved as predicted), **NEUTRAL**, or
**ANOMALOUS** (kept ≈ 0, one board starved, a source silently at 0, histogram
collapse) — but do NOT misread a LinkedIn same-UTC-day zero or a closed-app
Cowork skip as a regression (those are troubleshoot-pipeline). Rising
`duplicate_role (Phase 2)` counts mean the Phase-1 dedup key is drifting —
a `extra_title_noise_tokens` / `role_seen_window_days` signal. Anomalous → offer
the stored rollback. Mark the watch resolved.

## DONE criteria

- Funnel decomposed with real numbers (or explain-only if Step 0 degraded).
- Any change: drafted as a translated diff, statically validated, backtested
  with honest confidence, confirmed via packet, backed up, applied with an
  integrity check, and logged with a rollback command.
- Empty-but-healthy pool (`candidates.json` is `[]`, Phase 1 ran clean) is
  reported as "quiet market, nothing to calibrate" — NOT treated as a fault.
- One lever changed; post-change watch scheduled.
