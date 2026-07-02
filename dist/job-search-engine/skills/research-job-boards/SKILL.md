---
name: research-job-boards
description: Research which job boards are worth adding as pipeline sources for a role (asks for the role if none is named). Use when the user says "research job boards for a role", "find job boards for QA engineers", "which boards should we add", "find more job sources", "where else can we search for jobs", "найди джоб-борды для роли", "какие борды подойдут для дизайнеров", "какие ещё борды добавить", "надо расширить источники", or wants to expand where the jobs pipeline searches. Live-verifies every candidate board and reports an integration path per board. Research and report only — it recommends changes but does not edit profile.yaml.
---

# job-search-engine — job-board research

Given a role, find and LIVE-VERIFY job boards worth adding to the pipeline,
and classify how each could be integrated. Output: a markdown report in the
working folder plus a short summary in chat (user's language). This skill
only researches — it never edits `profile.yaml`, `engine/`, or state files.

## Step 0 — Inputs

1. **Role** (required): take it from the user's request ("research boards for
   Senior QA"). If no role was named, ask — do not guess one.
2. **Department context** (optional): if a working folder is mounted (glob
   `**/profiles/*/profile.yaml`, ignoring `profiles/_template/`; ask which
   profile if several real ones remain), read the profile for target geo /
   remote policy, enabled sources and current `sources.serpapi.queries`; read
   `rubric.md` for region and language constraints. No working folder →
   proceed with the template rubric's defaults as assumptions (remote-first;
   rich regions per `profiles/_template/rubric.md`) and say so in the report
   header.
3. **Web access**: use the session's web search / page fetch / browser tools.
   The run-pipeline skill's "no WebFetch, no WebSearch" rule is that skill's
   rule, not this one's — research requires the live web. If no web tool
   works in this session, stop and tell the user this skill cannot run here;
   never produce a report from memory.
4. Never spend the department's `SERPAPI_KEY` budget on research, and never
   read `.env` or OAuth files.

## Step 1 — Collect candidates (target 10–20 before verification)

Search in several passes and collect every plausible board:
- "best job boards for <role>", "niche job boards <stack/niche>"
- community mentions for the niche (Reddit, HN, awesome-lists)
- the usual remote set (Remotive, Himalayas, Wellfound, ...) — same
  verification bar as everyone else, no free passes for famous names.
Skip boards already enabled in the profile (serpapi / linkedin_brightdata) —
list them in the report as "already connected".

## Step 2 — Live verification (every candidate)

Open each board and record evidence; memory or blog claims don't count. A
board that can't be reached right now is marked "unverified", not guessed.
Budget: about 6 fetches per board; if more than ~15 candidates survive
Step 1, verify the 15 most promising and list the rest in the report as
"collected, not verified".
1. **Fresh volume**: search the board for the role; estimate postings from
   the last 7 days from the first results page (mark it approximate). Almost
   none → verdict "weak". Note missing/unreliable posting dates (Phase 1
   marks such domains `date_suspect`; the rubric scores them down).
2. **Link quality**: open 1–2 postings; is there a stable per-posting URL?
   Phase 1 only drops bare-domain/root links (`_is_search_or_root` in
   `engine/main.py`) — list pages WITH a path slip through to the sheet, so
   a real direct posting URL is essential, not just nice to have. While the
   posting is open, check its source for `JobPosting` JSON-LD (feeds check 5).
3. **Machine access**: RSS feed? public JSON API? plain HTML? or blocked
   (login wall, aggressive anti-bot)? Probe common paths (`/rss`, `/feed`,
   `/api`) and check the page source before concluding "HTML only".
4. **Geo/remote fit**: does the inventory match the Step 0 regions and remote
   policy, or is it dominated by out-of-scope geographies?
5. **Google Jobs presence**: `JobPosting` JSON-LD from check 2 is the real
   signal (that is what Google Jobs ingests); a Google search whose jobs
   panel shows postings "via <board>" confirms it. A plain `site:` hit only
   proves web indexing — weak evidence, never promote to path A on it alone.

## Step 3 — Integration path (classify every kept board)

- **A — already reachable via SerpAPI/Google Jobs**: recommend concrete
  additions to `sources.serpapi.queries` in `profile.yaml`, labelled
  "confirm with one google_jobs test query before adopting". Zero code; mind
  the SerpAPI budget (250 req/month ≈ 8 queries/day TOTAL, existing queries
  included).
- **B — RSS feed**: cheapest engine addition — a new
  `fetch(profile) -> list[Posting]` connector that parses a category feed
  (model: the `Posting` / `fetch` contract in `engine/sources/__init__.py`).
  Record the exact feed URL for each relevant category.
- **C — public JSON API**: small new connector on the same contract. Record
  endpoint, auth requirements, rate limits.
- **D — dataset/scraping vendor** (model:
  `engine/sources/linkedin_brightdata.py`): per-record cost decision; name
  the vendor and pricing model if visible.
- **E — not integrable now**: login wall / anti-bot / no dates AND no direct
  links. Keep in the report with the reason so it isn't re-researched later.

Paths B–D are engine changes (repo invariant: logic lives only in `engine/`).
The report recommends; a developer decides and implements.

## Step 4 — Report + summary

Write `research/boards_<role-slug>_<date>.md` in the working folder (create
`research/` if missing; no working folder → print the full report in chat).
`role-slug` = lowercase ASCII, non-alphanumerics collapsed to `-`, non-Latin
role names transliterated (e.g. senior-react-developer); `date` = today as
`YYYY-MM-DD`.
1. Header: role, date, department context used (profile name or "template
   defaults"), counts: candidates found / verified / kept.
2. Summary table: Board | Fresh/week | Direct links | Access | Geo fit |
   GJobs | Path | Verdict. Unverified boards get verdict "unverified" and an
   empty Path.
3. Per-board evidence: URLs checked, counts seen, dates, quirks. Every table
   claim must trace to a line here.
4. **Next steps**, ordered by cost: path A first (ready-to-paste query
   strings), then B (feed URLs), C, D. Fewer than 3 boards kept → say so
   plainly and recommend the fallback: tune existing
   `sources.serpapi.queries` or broaden the role. Still write the report.

No secrets or per-department private data in the report — it must be safe to
share outside the department. In chat, give the top 3–5 boards with one-line
reasons and the path breakdown; point to the report file for the rest.
