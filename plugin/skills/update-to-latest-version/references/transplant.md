# Transplant re-onboarding (fork path, Step U1)

For deployments that predate the plugin architecture or have forked away from it
(no `profile.yaml`, config in a bare `.env`, `pipeline/main.py` instead of
`engine/`, hardcoded `QUERIES`, extra source modules the plugin never shipped —
the uiux and Unity classes). They share no merge anchors with the plugin layout,
so there is nothing to three-way-merge against. An in-place upgrade does not
exist for them — you rebuild on the current architecture and **carry the
department's intent across**, using the setup interview as the merge tool
(Claude reads the old config and pre-fills the answers).

Never attempt an automated file merge across an architecture boundary, and never
edit the fork in place — build a fresh working folder alongside it.

## What to extract (the organs)

Read the old deployment in explain-only mode and carry these into a freshly
templated deployment:

- **Query intent** — old hardcoded `QUERIES` / `.env` queries → the current
  template's `sources.serpapi.queries` and LinkedIn `inputs`. Regenerate from the
  template with the old values slotted in; never copy the old config file.
- **Gate knowledge** — deny/allow lists (or their fork equivalents) → the new
  `relevance_gate` + seed `tests/test_gate_<dept>.py` cases from them.
- **Rubric department sections** — business context, role-type policy,
  hybrid-skill killers, vendor exclusions → paste under the current template's
  frozen headings.
- **Dedup state — the crown jewels.** `seen_urls` and `role_seen` (convert the
  format if the fork differs; role keys are `<company>|<title>`) plus
  `blocked_domains` copy into the new `state/`. This is what prevents
  re-leading the same vacancies after cutover. `company_size_cache.json` copies
  if present.
- **Secrets** — `.env` keys and `oauth_*.json` reuse as-is (same Google account).

Do **not** carry `write_queue.json` (drain it in the fork's final run, or log its
pending entries as consciously abandoned) or `linkedin_state.json` (the UTC
run-once guard self-resets).

## Sheet

Keep it — it holds the manual columns (L/M feedback), sales reps' bookmarks, and
lead-id history. Migrate its header to the current layout (A–Q per
`sheet-template.md`) and **continue lead ids from the existing max** (override
setup's default "start at `<PREFIX>-0001`"). Only start a fresh sheet if the
fork's layout is irreconcilable; then freeze the old sheet read-only and rebuild
`seen_urls`/`role_seen` from its rows (each row has URL + company + title) so
dedup history survives — dedup lives in state, not the sheet.

## Cutover (one machine per department — sequencing, not distributed systems)

1. Disable the old Task Scheduler job AND the old Cowork task; **verify** both
   disabled.
2. Extract the organs (above).
3. Run `setup-search-engine` with the extracted values as pre-answers into a NEW
   working folder.
4. Migrate/keep the sheet; set the id continuation.
5. Proving run: Phase 1 on the host, Phase 2 writes 1–3 rows; verify cells + id
   continuity + no double-write of a vacancy already in the old sheet.
6. Register the new schedules in the same staggered slot the fork used.
7. Archive the old working folder after ~a week (it's the rollback) — don't
   delete it on cutover day.
