# Safe-change procedure (Steps 5, 7, 8)

## Corpus for backtesting

The engine records no per-vacancy drop reasons, so backtesting replays triage
offline. Corpus = today's `profiles/<dept>/candidates.json` plus archived
snapshots the skill keeps in `profiles/<dept>/calibration/corpus/candidates_<date>.json`
(archive a copy at the start of each session; retention 14 days). State files
(`seen_urls.json`, `role_seen.json`, `blocked_domains.json`) are opened
**READ-ONLY** in replay. Corpus holds real vacancy payloads — never commit it
into the plugin repo (the build's privacy guard would fail).

## Offline backtest (free — the default)

Import from the deployment's own `engine/` (never the repo copy):

```python
from engine.profile import load_profile
prof = load_profile("profiles/<dept>/calibration/pending")  # compiles DRAFT
gate = prof.gate                                  # already-compiled RelevanceGate
for c in corpus:                                  # candidate dicts
    v = gate.classify(c["title_guess"], c.get("raw_content", ""))
    # v.relevant / v.reason  ← the reason production discards via is_relevant()
```

(`load_profile(path)` compiles the drafted gate into `prof.gate`; the raw YAML
is on `prof.raw`. Filter defaults extended by `extra_*` keys are on
`prof.title_noise_tokens` / `prof.unreliable_date_domains` /
`prof.serpapi_excluded_hosts` / `prof.excluded_companies`.)

Then replay the mechanical filters (`apply_filters` order: no_link →
blocked_domain → duplicate → duplicate_role → excluded → date-null → too_old)
against the same corpus. Emit a per-vacancy delta table:

| id | title | old | new | stage | reason |
|---|---|---|---|---|---|
| … | … | KEPT | DROPPED | too_old | date < now − max_age_hours |

Plus per-stage count deltas. **Confidence:** gate/filter TIGHTENING and rubric
edits are trustworthy offline. Gate/filter LOOSENING is NOT — postings the old
gate dropped were never persisted, so the corpus can only show recall LOSS, not
recall GAIN. Say so explicitly; do not present a green backtest as proof a
loosening worked.

## Rubric backtest (free)

Re-score a 10–20 vacancy sample from the corpus against the OLD and the NEW
`rubric.md` in-session; show both histograms in the frozen
`Score 1: N | 2: N | 3: N | 4: N | 5: N` format. LLM re-scoring is
nondeterministic — compare against a multi-day baseline, not a single run, and
label it as an estimate.

## Live A/B fetch (paid — only with explicit consent)

The only way to validate a gate LOOSENING. Guard rails, all required:
- Confirm the day's SCHEDULED Phase-1 run already ran (check
  `logs/fetch_*.log`). A dry run BEFORE it burns SerpAPI budget AND writes
  `state/linkedin_state.json` (trigger-time), zeroing the evening LinkedIn run.
- In the test profile copy set `sources.linkedin_brightdata.enabled: false`
  (only `SEEN_URLS_FILE` is env-redirectable; `role_seen.json` and
  `linkedin_state.json` are NOT — disabling LinkedIn is the only safe way).
- Redirect state and outputs to scratch, cap the SerpAPI spend, get consent for
  the exact query count (default ≤ 2 of the 8/day budget):

```
$env:SEEN_URLS_FILE = "profiles/<dept>/calibration/scratch/seen_urls.json"
python -m engine.main --profile profiles/<dept>/calibration/pending `
  --out profiles/<dept>/calibration/scratch/candidates_test.json `
  --report-out profiles/<dept>/calibration/scratch/report_test.json
```

Compare the scratch report's `source_counts` / `filter_counts` against the live
baseline. Never point `--out` at the live `candidates.json`.

## CALIBRATION_LOG.md entry (Step 7 — append-only)

```
## 2026-07-03T14:20Z — 3d
Intent: "больше 3D-artist лидов из Германии" (user's words)
Files: profile.yaml
Change: weak_titles += '\b3d\s+artist\b' with accept_context '(blender|maya|zbrush)'
Backtest: corpus 58 → +6 DROPPED→KEPT, 0 KEPT→DROPPED (tightening N/A; loosening
  — offline can't confirm gain, live A/B pending)
Baseline: filter_counts {duplicate:41,duplicate_role:12,too_old:9}; hist 18|21|9|4|1
Expected: +~4–6 candidates/day, mostly DE
Watch: open (compare after 1–3 runs)
Rollback: Copy-Item profiles/3d/calibration/backups/profile.yaml.2026-07-03T1420Z.bak profiles/3d/profile.yaml
```

## Rollback (Step 8)

`Copy-Item <backup> <live>`, then re-run Step 4 (dry-run compile + gate tests)
to prove the restored state compiles and passes. If the rolled change added
cases to `tests/test_gate_<dept>.py`, revert or re-run them — a restored `.bak`
alone desyncs tests from the profile. Append a ROLLBACK entry. Rollback restores
FILES, not consequences: `seen_urls` / `role_seen` entries, sheet rows, and
vacancies already dropped under the bad config are permanent.

## Cross-department porting

`rubric.md` headings are frozen so a fix ports cleanly. To apply a calibration
to a second department, re-run this skill on that profile and re-diff — never
copy a whole file across departments (queries, gate, sheet id differ).
