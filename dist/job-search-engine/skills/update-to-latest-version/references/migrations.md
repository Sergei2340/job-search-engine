# Per-release migrations (Step U2)

One entry per release that touches any working-folder surface. The newest
plugin ships the full cumulative list; Step U2 selects the PENDING entries by
evaluating each entry's Preconditions against the deployment (version range is
only a hint — a partially-upgraded folder can have older migrations still
pending). Each entry is a proposal set for Step U6/U7 — nothing here is applied
without the user's approval.

## Version-base mapping (Step U6)

The three-way merge base is the template at the deployment's version, shipped in
`assets/profiles/_template_history/<ver>/`. Snapshots exist for **0.4.2, 0.5.0,
0.6.0** (and the current version). Floor rule:

- **Deployment < 0.5.0 → base = `_template_history/0.4.2/`.** The rubric template
  was byte-identical from 0.1.0 through 0.4.2, so 0.4.2 is an exact rubric base
  for any pre-0.5.0 deployment. Two known cosmetic-noise classes when the profile
  base is 0.4.2:
  - 0.3.0–0.4.1 `profile.yaml` differs only by a 3-line header comment (a
    dangling `docs/ADD_DEPARTMENT.md` pointer) — expect one spurious "user
    changed" hunk; ignore it.
  - ≤ 0.2.0 `profile.yaml` also carried `weworkremotely:` / `remoteok:` source
    blocks (removed at 0.3.0) — a 0.4.2 base would misread those as user-added.
    In practice no such plugin deployment is known to exist; if one appears,
    route it to `transplant.md`.
- **0.5.0 → base = `_template_history/0.5.0/`.** Note its `profile.yaml` is
  byte-identical to 0.4.2's — expected, not an error.

The engine manifest lookup (Step U0.4) is independent of this and keyed by hash,
not by declared version.

---

## Migration: → 0.5.0 (Company-size preference in scoring)

**Surfaces:** `rubric.md` only. No engine change (0.5.0 added the `company:giant`
flag to `engine/SKILL.md`, which reaches the deployment via the normal engine
REPLACE in Step U5 — no separate action). No sheet change. No profile change.

**Preconditions:** `rubric.md` has NO `## Company-size rule` heading.

**Actions (rubric, one lever = three coupled section edits):**
1. **Insert** the `## Company-size rule` section verbatim from the new template,
   at the anchor **between `## DACH language rule` and `## Score 2 — minimum
   bar`** (NOT near the bias section — the bias section is last and unrelated).
2. **Rework `## Score 4`**: company-size fit (~11–500, sweet spot 50–200) becomes
   the primary positive signal; "well-known company" removed; "well-funded"
   narrowed to "recently funded (seed–C)".
3. **Extend the soft-negatives paragraph** under `## Hard negative signals`:
   add "giant employer per the Company-size rule below — record `company:giant`
   in `risk_flags`".

Run all three as the three-way merge of Step U6: if the department customized
Score 4 or the soft-negatives line, that section is a CONFLICT (decision packet,
both versions shown), not a silent overwrite.

**Idempotency marker:** `## Company-size rule` heading present.

**Verification:** rubric still ends with `## Explicit bias instruction`;
re-score a 10–20 vacancy sample old-vs-new and show both histograms (labeled an
estimate) per triage-calibration Step 5.

**Rollback:** `Copy-Item` the `rubric.md.<ts>.bak`.

**Expected effect:** some existing 4s ("well-known company") drop to 3; giants
drop a band (e.g. 3 → 2). Set this expectation in the CALIBRATION_LOG so the
Step-9 watch doesn't misread it as ANOMALOUS.

---

## Migration: → 0.6.0 (Company-size enrichment + Headcount sheet column)

**Surfaces (in this order):** engine → profile.yaml (opt-in) → rubric.md → sheet.
The order matters; the sheet's `E1` sentinel makes a wrong order a clean stop,
not corruption.

**Preconditions:** engine lacks `company_enrich.py`; `profile.yaml` lacks the
`enrichment:` block; sheet `E1` reads `Board` (16-col A–P layout).

**Actions:**
1. **Engine** — standard Step U5 REPLACE (brings `company_enrich.py`, `_util.py`,
   the parameterized `_poll_snapshot`, the A–Q writer contract in the
   run-pipeline skill). Nothing rubric- or profile-specific here.
2. **profile.yaml — additive opt-in.** Offer the top-level `enrichment:` block
   (from the new template) as an explicit choice, stating the cost: enabling
   `enrichment.company_size` starts Bright Data company lookups (~$1.5/1K, 5K/mo
   free per account, cached — near-zero steady state) and requires subscribing
   to the "LinkedIn companies — collect by URL" dataset (`gd_l1vikfnt1wgvvqz95w`).
   Default in the template is `enabled: true`; if the user declines, insert the
   block with `enabled: false` (Headcount then shows `Unknown`). Also update the
   `tab:` comment `columns A-P` → `A-Q`. Do not touch anything else in the file.
3. **rubric.md** — three-way merge of the single delta: Company-size rule
   **detection step 1** now names the candidate's `company_size` field as primary
   evidence, `raw_content` phrases as secondary. If the department customized that
   step → CONFLICT packet.
4. **Sheet** — follow the setup-search-engine `references/sheet-template.md`
   section "Migrating a pre-0.6.0 sheet" verbatim (pause → insert a column left
   of Board → title `E1` `Headcount` → update plugin → re-enable). Do not restate
   the procedure here.

**Idempotency markers:** `engine/company_enrich.py` exists; `enrichment:` block
present (either enabled value counts as "migration offered/done"); rubric step 1
names `company_size`; sheet `E1 == Headcount`.

**Verification:** offline trio green; a proving run writes A–K and N–Q with L/M
untouched; `last_run_report.json` carries a `company_enrichment` block.

**Rollback:** engine rename-back; `rubric.md`/`profile.yaml` from `.bak`; sheet
forward-only after the first A–Q row (before it: delete the inserted column,
restore the `Board` title).

---

## Release discipline (for whoever ships the next version)

Repo-facing, one rule here: every release that changes a working-folder surface
**adds an entry to this file**. The full canonical checklist (template snapshot,
manifest, CHANGELOG note, compatibility rule, dist refresh) lives in the plugin
repo's root README — follow it there; this shipped copy deliberately does not
restate it.
