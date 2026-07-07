---
name: update-to-latest-version
description: Upgrade an already-deployed job-search-engine working folder to the installed plugin version WITHOUT losing the department's customizations. Use when the user says "обнови пайплайн", "обнови движок", "обновись до последней версии", "новая версия плагина — что делать", "update the pipeline", "update the engine", "upgrade to the latest version", or has just reinstalled a newer plugin and wants their deployment brought up to date. Compares the deployed files against the templates of their version and the new templates, then proposes each change with a plain-language explanation and applies only what the user approves. For chronic tuning of a working pipeline use triage-calibration; for a broken run use troubleshoot-pipeline; for first-time setup use setup-search-engine. Requires a working folder set up by the setup-search-engine skill.
---

# job-search-engine — update a deployment to the latest version

Bring a department's working folder up to the installed plugin version while
**preserving every customization** (queries, relevance gate, department rubric
sections, filters, blocked domains, dedup state, the sheet). Talk to the user
in their language (usually Russian); keep it non-technical unless asked.

Core method — **three-way, never two-way.** A deployed file =
`template@its-version` + department edits. Comparing it only against the new
template cannot tell "the user customized this" from "the template moved on".
So every profile/rubric change is decided against **both** the base (the
template at the deployment's version, shipped in
`assets/profiles/_template_history/<ver>/`) **and** the new template. Nothing is
applied silently: each change is a **proposal with a plain-language reason**;
the user picks. Only `engine/` — "never hand-edited" by contract — is replaced
wholesale, and only after it verifies clean against its version's manifest.

**Reuse, don't reinvent.** This skill runs on top of triage-calibration's
machinery — do not redefine any of it:
- draft edits in `profiles/<dept>/calibration/pending/`, show a translated diff,
  re-diff against the live file immediately before applying;
- back up to `profiles/<dept>/calibration/backups/<file>.<UTC-timestamp>.bak`;
- append to `profiles/<dept>/calibration/CALIBRATION_LOG.md` (template in
  triage-calibration `references/safe-change.md`);
- static gate: compile via the deployment's own `engine.profile.load_profile()`,
  run `test_gate_<dept>` / `test_triage_filters` / `test_e2e_offline`;
- post-change watch = triage-calibration Step 9 (re-invoke after 1–3 daily runs;
  CONFIRMED / NEUTRAL / ANOMALOUS against the logged baseline).

Per-release specifics (what each version changed, in what order, with which
guards) live in `references/migrations.md`. The fork path lives in
`references/transplant.md`.

## Step U0 — Locate + fingerprint

1. Glob `**/profiles/*/profile.yaml` across mounted folders (ignore `_template`
   and `_template_history`; refuse the plugin repo's own `profiles/` and any
   `dist/`). Several deployments → STOP and ask which department; never guess.
2. **Integrity first** (the known corruption class — NUL padding, truncated
   tails). NUL-scan + expected-tail check (`profile.yaml` last key; `rubric.md`
   ends with the bias section) + `python -m py_compile` on every `engine/*.py`.
   A corrupt file fingerprints as the wrong version — repair via
   troubleshoot-pipeline BEFORE proceeding.
3. **Lineage.** In-chain layout = `engine/main.py` + `engine/relevance.py` +
   `profiles/<dept>/profile.yaml` present and `load_profile()` compiles.
   Anything else (`pipeline/main.py`, config in a bare `.env`, hardcoded
   `QUERIES`, an extra source module the plugin never shipped) → a pre-plugin
   **fork** → go to `references/transplant.md`. Do not attempt an in-place
   upgrade across an architecture boundary.
4. **Determine the deployment's actual version — by evidence, not by claim.**
   The working folder's `ENGINE_VERSION` file (format `X.Y.Z (YYYY-MM-DD)`) is a
   *hint* only (older setups never wrote a fixed artifact). Authoritative =
   hash the deployed engine files (`engine/**` except `__pycache__`, plus
   `scripts/get_oauth_token.py`, LF-normalized) and match the set against every
   `assets/manifests/*.sha256`:
   - **exact match to version V** → the engine is intact and is version V;
   - **matches no manifest** → some engine file differs from every release →
     it is either hand-edited (a broken contract) or corrupt → treat as
     MODIFIED (Step U5), do not trust the declared version;
   - two manifests are byte-identical when a release didn't touch the engine
     (e.g. 0.4.1 ≡ 0.4.2, 0.6.0 ≡ 0.7.0) — matching either is fine, the engine
     is current-enough for that range.
   Also record the per-surface marker vector for later steps: is
   `## Company-size rule` present in `rubric.md`? does `profile.yaml` carry the
   `enrichment:` block? what does the sheet's `E1` read? These say which
   migrations already landed (a partially-upgraded folder is normal, not an
   error — see the compatibility rule in the root README).
5. **Target = the installed plugin version** (`assets/ENGINE_VERSION`).

## Step U1 — Route

- Deployed version == target and all markers current → report "already up to
  date", stop.
- Corrupt (U0.2) → troubleshoot-pipeline first.
- Fork (U0.3) → `references/transplant.md`.
- In-chain and behind → continue.

## Step U2 — Compute the migration delta

Read `references/migrations.md`. List every migration entry between the
deployment's version and the target, **in order**. A deployment several
versions behind replays them sequentially — the newest plugin ships the whole
cumulative list, so a direct 0.4.2→current jump needs no intermediate plugin
installs. Show the user the ordered list of what will be proposed and why,
before touching anything.

## Step U3 — Baseline

Run the offline test trio green **before** any change (red baseline → you can't
attribute a later failure; fix via troubleshoot-pipeline first). Archive the
last `filter_counts` and score histogram line from
`reports/`/`last_run_report.json` as the Step-U9 watch baseline.

## Step U4 — Quiesce

Pause BOTH schedules with the user's consent — the Cowork Phase-2 task and the
host's Phase-1 Task Scheduler job — and confirm no `logs/fetch_*.log` is
mid-write. An upgrade must never race the pipeline it upgrades. Staggered hours
are a fleet contract (shared Bright Data key + Google account); never move a
slot silently.

## Step U5 — Engine refresh (REPLACE, never merge)

`engine/` is contract-frozen, so it is replaced whole, not patched — but verify
before clobbering:

- **Intact (matched a manifest in U0.4):** copy-verify-swap. Stage the plugin's
  `assets/engine/**` + `scripts/get_oauth_token.py` into `engine.new/`,
  `py_compile` everything + NUL/tail check + run the offline trio against it,
  then rename `engine/` → `engine_pre_<oldver>/` and `engine.new/` → `engine/`.
  Two renames, no partial state. Rollback = rename back.
- **Corrupt:** replacement IS the fix; log it as the corruption class, proceed.
- **MODIFIED (matched no manifest):** STOP — never clobber a diff you haven't
  read. Diff each differing file against the plugin's `assets/engine/` copy and
  triage WITH the user:
  - a file the plugin never shipped (e.g. a custom `engine/sources/<board>.py`
    the department added) → **carry it forward**: copy it into the new
    `engine/`, and re-apply its registration line in `main.py`'s source
    registry on top of the new `main.py` — show that one-line diff for approval.
    Recommend upstreaming the source to the shared repo so future upgrades stop
    requiring this manual carry.
  - a shipped file changed with no upstream equivalent (a local hot-fix) → a
    **fork event**: preserve it in the backup, surface it, and the sanctioned
    resolution is to upstream the fix to the repo first, then upgrade. An
    upgrade never silently carries a private engine patch forward.

Never touch `state/` here (or anywhere): schemas migrate lazily on the engine's
next normal atomic run. `state/blocked_domains.json` is user calibration capital
despite living under `state/` — never touch it.

## Step U6 — Profile / rubric: three-way, proposal per migration

For each pending migration (U2), base = `assets/profiles/_template_history/<the
deployment's version>/`. If the deployment is below the oldest shipped snapshot,
use the floor mapping in `references/migrations.md` (pre-0.5.0 → base 0.4.2).

**rubric.md — section 3-way by `##` heading** (headings are the frozen merge
anchors):

| base→new template | base→live (user) | action |
|---|---|---|
| unchanged | changed | keep the user's section — it's their calibration |
| changed | unchanged | replace with the new template's section (anchored) |
| changed | changed | **CONFLICT** — decision packet: show both versions + a plain-language explanation; user picks keep / take-new / hand-merge |
| new section | — | insert verbatim at the template-specified anchor (migrations.md names it), as one lever |
| deleted | — | propose via packet only; never silent deletion |

**profile.yaml — key-path 3-way, additive-only.** Default is **no change** (the
compatibility rule guarantees a new engine runs an old profile identically). A
release may only *offer* a new block (e.g. `enrichment:`) as an explicit opt-in,
stating the cost consequence; never regenerate the file, reorder keys, or touch
`queries`, `relevance_gate`, `filters`, caps, or `sheet.spreadsheet_id`.

Apply every accepted change through triage-calibration's pipeline (pending draft
→ translated diff → `load_profile()` compile on the NEW engine → gate tests →
decision packet → backup → atomic apply → CALIBRATION_LOG entry). **If the live
rubric's headings don't match the base template's set/order** (anchors gone) →
degrade to explain-only: emit a manual per-section porting checklist and stop —
do not 3-way-merge on missing anchors.

## Step U7 — Sheet migration (if the release includes one)

Follow the canonical procedure in the setup-search-engine skill's
`references/sheet-template.md` (do not restate it) — pause first, insert the
column, retitle, update, re-enable. The writer's own sentinel (e.g. `E1` must
read `Headcount` since 0.6.0) converts a wrong-order migration into a clean stop
rather than a shifted write. The sheet and the plugin version roll back as a
pair or not at all.

## Step U8 — Finalize

1. Copy the plugin's `assets/ENGINE_VERSION` verbatim to
   `<working folder>/ENGINE_VERSION` — **last**, as the commit marker (new
   engine + old stamp = "upgrade in flight/failed", which the next U0 catches).
2. Append an **UPGRADE** entry to `CALIBRATION_LOG.md` (same log, one audit
   trail per department): from→to versions, engine verdict (intact / repaired /
   carried-forward files), rubric sections merged vs conflicted, sheet migration
   timestamp + first post-migration row id if any, the baseline from U3, and the
   exact rollback commands per surface.

## Step U9 — Resume + prove + watch

Re-enable both schedules. Proving run: Phase 1 on the host, Phase 2 writes ≥1
row, verify the cells (and, for a sheet migration, that A–Q land in the right
columns and L/M stay untouched). Then the triage-calibration Step-9 watch: ask
the user to re-invoke after 1–3 daily runs; compare `source_counts` /
`filter_counts` / histogram against the U3 baseline; CONFIRMED / NEUTRAL /
ANOMALOUS → on anomalous, offer the stored rollback.

## Rollback (per surface)

- **engine/**: rename `engine_pre_<oldver>/` back; restore `ENGINE_VERSION`.
- **profile.yaml / rubric.md / gate tests**: `Copy-Item` from the `.bak`, then
  re-run compile + tests (revert added gate-test cases too, or they desync).
- **state/**: nothing — upgrades never write it.
- **sheet**: forward-only after the first A–Q row lands (rolling back would
  shift human data in L/M); before that, delete the inserted column and restore
  the title. Roll code forward, not the sheet back.
- What rollback never undoes (state honestly): `seen_urls`/`role_seen` entries,
  rows already written, vacancies dropped under the interim config.

## DONE criteria

- Deployment fingerprinted (or routed to transplant/troubleshoot); engine
  intact-verified before replace; every profile/rubric change proposed with a
  reason and applied only on approval; sheet migrated via the canonical
  procedure if required; `ENGINE_VERSION` stamped last; UPGRADE logged with
  rollback commands; proving run green; Step-9 watch scheduled. No customization
  lost, or the divergence surfaced and consciously resolved.
