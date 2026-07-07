# Parameter map (Step 2)

Every tunable knob, its blast radius, and its couplings. Danger: 🟢 safe /
🟡 has couplings, explain before changing / 🔴 can silently break the funnel.
Change **one lever per session**.

## Symptom → lever (start here)

| User says (RU) | First lever | Why / caveat |
|---|---|---|
| "мало лидов" / too few | widen `allow_titles` / `weak_titles`; raise `candidate_cap`; add SerpAPI query (≤ 8/day) | first confirm it's not a quiet market (empty `[]` pool) or an acute failure → troubleshoot |
| "много мусора в таблице" | tighten `rubric.md` bands / add hard negative; add `deny_titles` | prefer rubric (Phase 2, reversible) over gate (Phase 1, invisible drops) |
| "гиганты в таблице" / "big companies don't answer" | rubric `Company-size rule` (giant soft negative; size-fit Score-4 signal) | soft → hard-negative escalation only after histogram/column-L evidence; pre-0.5.0 rubrics lack the section — port it verbatim |
| "джуны проскакивают" | rubric Role-type / Score-2 wording | NOT a gate job — seniority lives in scoring, not titles |
| "в Headcount одни Unknown" | `enrichment.company_size.enabled`; BRIGHTDATA_API_KEY presence | if it never worked or broke suddenly → troubleshoot-pipeline ("Headcount column all Unknown"); this skill only owns the knobs |
| "повторы одной вакансии" | `role_seen_window_days` ↑; `extra_title_noise_tokens` | tokens re-key dedup in BOTH phases (see 🔴 below) |
| "мёртвые / paywall ссылки" | `state/blocked_domains.json` (🟢 fast path) | one host per line; keys starting `_` are comments |
| "эта компания — не лид" | `filters.excluded_companies` + rubric vendor text | must edit BOTH or phases desync |
| "мало из <страны>" | add SerpAPI `{q, location, gl}` / LinkedIn `inputs` pair | budget: SerpAPI 8/day, LinkedIn billed per record |
| "почему эту не взяли" | Step 1b trace (no edit) | recovers the discarded gate reason |

## Phase 1 — `profile.yaml`

### `sources.serpapi`
- `queries` (🟡) — list of `{q, location?, gl?, hl?}`. Each entry = 1 SerpAPI
  request/day. **Hard cap 8/day** on the 250-req/month tariff; count existing
  entries before adding.
- `date_posted_chip` (🟡) — server-side freshness (`"date_posted:3days"`;
  `null` disables). This, not `max_age_hours`, is the real SerpAPI freshness
  window.
- `enabled` (🟢) — off self-skips the source.

### `sources.linkedin_brightdata`
- `inputs` (🔴 cost) — keyword × geo pairs; **billed per record**. Keep lean.
- `time_range` (🔴 cost) — e.g. `"Past 24 hours"`. The `limit` params are sent
  but IGNORED by the dataset — `time_range` is the ONLY LinkedIn volume/cost
  cap.
- `run_once_per_day` (🔴 do not flip) — the daily UTC guard; leave `true`.

### `enrichment.company_size` (since 0.6.0 — fills the sheet's Headcount column)
Top-level `enrichment:` block, NOT under `sources:` (a `sources.*` entry the
engine doesn't recognize logs an "unknown sources" warning every run).
- `enabled` (🟢) — off → every candidate gets `company_size: null`, Headcount
  shows `Unknown`, scoring falls back to raw_content phrases + LLM knowledge
  (rubric Company-size rule steps 1-secondary/2). Safe both ways. Defaults ON
  in the template, but OFF when the block is absent entirely (so refreshing
  only `engine/` on a pre-0.6.0 deployment never starts surprise billing).
- `max_per_run` (🟡 cost) — cap on UNCACHED companies sent to the Bright Data
  companies dataset per run; over-cap companies stay `null` this run and are
  fetched the next time they surface a new posting. Cost: $1.5/1K lookups,
  5K/month free, and the cache (`state/company_size_cache.json`) means each
  company is billed about once ever — raising this mostly affects the first weeks.
- `ttl_days` / `negative_ttl_days` (🟢) — how long a positive / no-data cache
  entry is trusted (defaults 180 / 30). Lowering re-bills lookups sooner.
  Staleness over blindness: if a refetch of an expired entry fails or is
  capped out, the expired bucket is still shown until the next successful
  fetch — an old size beats `Unknown`.
- `dataset_id` / `max_poll_seconds` (🟢 rarely) — override the Bright Data
  companies dataset id / the snapshot wait budget (default 240s); defaults in
  `engine/company_enrich.py`.

### Mechanical filters
- `candidate_cap` (🟢) — max candidates/run into Phase 2 (LLM cost guard);
  round-robin per board, no-date postings dropped first when over cap.
- `max_age_hours` (🟡) — drops postings older than N hours, BUT only among those
  the fetch windows already returned (capped by `date_posted_chip` /
  `time_range`). Postings with **no date always pass**.
- `role_seen_window_days` (🟡) — cross-run dedup window for `(company, title)`;
  location ignored, seniority preserved (Senior ≠ Junior).
- `filters.excluded_companies` (🟡) — exact lower-cased company match; mirror in
  rubric vendor text.
- `filters.extra_title_noise_tokens` (🔴) — stripped from titles before dedup
  keying, in BOTH phases, compared against historical `state/role_seen.json`.
  NEVER add seniority words (`senior`, `lead`, `junior` — test-pinned) or past
  dedup keys silently shift.
- `filters.extra_unreliable_date_domains` (🔴 dual effect) — nulls the date
  (rescues from `too_old`) AND stamps `date_suspect: true`, which is a `-1` hard
  negative at scoring. Not a pure recall knob.
- `filters.extra_serpapi_excluded_hosts` (🔴 substring) — a link is dropped if
  any listed token is a **substring** of its host. `jobs` would kill almost
  everything; use full hostnames.

### `relevance_gate` (🔴 invisible drops)
Decision order, first hit wins (all regexes case-insensitive, single-quote in
YAML): `deny_titles` → `disambiguate` → `allow_titles` → `weak_titles` →
default deny. Empty gate → `GateConfigError`, Phase 1 aborts.
- `deny_titles` — TITLE regex; drops outright, **beats allow**. Widen carefully:
  a broad deny is an invisible recall killer.
- `disambiguate` — `{title, accept_context?, reject_context?}`: rejects only
  when `reject_context` hits the body AND `accept_context` does not; else
  accepts (recall-favouring).
- `allow_titles` — TITLE regex → relevant.
- `weak_titles` — `{title, accept_context}`: relevant only with `accept_context`
  in title+body; a weak match WITHOUT context is rejected (no fall-through).
Every gate edit → add test cases first, then green tests (SKILL Step 4).

## Phase 2 — `rubric.md` (preserve every heading verbatim)
- **Score 1 / Hard negative signals / Soft negatives** — what disqualifies or
  downgrades; `-1` per hard negative, floor 2, two hard negatives = score 1.
  Tightening here is the reversible way to cut junk.
- **Score 2 / 3 / 4 / 5** — the positive bands (region list, salary floor,
  agency/staff-aug signal).
- **Company-size rule** (since 0.5.0) — size bands (11–500 fit, 50–200 sweet
  spot) + giant soft negative `company:giant`. Absent in pre-0.5.0 department
  rubrics: porting = insert the whole section verbatim **between `## DACH
  language rule` and `## Score 2 — minimum bar`** + rework Score 4 + extend the
  soft-negatives line, as ONE lever. (The update-to-latest-version skill does
  this automatically as its → 0.5.0 migration.)
- **Role-type policy** — the precision backstop; where seniority / adjacent-role
  caps live.
- **Explicit bias instruction** — recall over precision. Do not delete; it is a
  cross-phase invariant.

## Hardcoded — NOT knobs (name them so users stop asking)
- `score ≥ 2` keep threshold — hardcoded in `engine/SKILL.md`; refuse, redirect
  to rubric-band tuning.
- `max_per_query = 30` (SerpAPI items/query), poll `15s` / timeout `900s`
  (LinkedIn), `raw_content` truncation `30000` chars — engine constants.
- Gate rule order, `apply_filters` order, fair-cap round-robin — engine logic.
- Sheet columns L / M — manual, never written.
- Headcount display rule (enriched bucket verbatim; `≈` only for recognized
  giants; else `Unknown`) — hardcoded in `engine/SKILL.md`, not a knob.
