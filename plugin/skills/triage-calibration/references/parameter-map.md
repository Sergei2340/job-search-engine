# Parameter map (Step 2)

Every tunable knob, its blast radius, and its couplings. Danger: 🟢 safe /
🟡 has couplings, explain before changing / 🔴 can silently break the funnel.
Change **one lever per session**.

## Symptom → lever (start here)

| User says (RU) | First lever | Why / caveat |
|---|---|---|
| "мало лидов" / too few | widen `allow_titles` / `weak_titles`; raise `candidate_cap`; add SerpAPI query (≤ 8/day) | first confirm it's not a quiet market (empty `[]` pool) or an acute failure → troubleshoot |
| "много мусора в таблице" | tighten `rubric.md` bands / add hard negative; add `deny_titles` | prefer rubric (Phase 2, reversible) over gate (Phase 1, invisible drops) |
| "гиганты в таблице" / "big companies don't answer" | rubric `Company-size rule` (giant soft negative; size-fit Score-4 signal) | soft → hard-negative escalation only after histogram/column-K evidence; pre-0.5.0 rubrics lack the section — port it verbatim |
| "джуны проскакивают" | rubric Role-type / Score-2 wording | NOT a gate job — seniority lives in scoring, not titles |
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
  rubrics: porting = insert the whole section verbatim before the bias
  section + rework Score 4 + extend the soft-negatives line, as ONE lever.
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
- Sheet columns K / L — manual, never written.
