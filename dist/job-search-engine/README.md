# job-search-engine (plugin)

Turn fresh job postings into sales leads for YOUR department: companies hiring
the roles you can staff are prospects for outsourcing / staff augmentation.
One shared engine; everything department-specific (search queries, relevance
rules, scoring rubric, Google Sheet, API keys) is generated for you during
setup and stays in your own working folder — this plugin ships no private data.

## Skills

- **setup-search-engine** — run **/setup-search-engine** (or say "set up the jobs pipeline"). End-to-end onboarding:
  environment checks (Chrome extension, Python, connectors), a short interview
  about your department's roles and markets, API keys (SerpAPI, optional
  Bright Data), Google Sheet + OAuth, profile generation with tests, and a
  proving run that writes real rows to your sheet before anything is scheduled.
- **run-pipeline** — the daily Phase 2: scores fetched candidates 1–5 against
  your rubric and writes score ≥ 2 rows to your sheet. Normally invoked by the
  scheduled task the wizard creates.
- **troubleshoot-pipeline** — say "pipeline didn't run" / "no leads today" /
  "sheet write blocked".
- **research-job-boards** — say "research job boards for `<role>`". Finds and
  live-verifies boards worth adding for a role, and reports each board's
  integration path (query tweak, RSS, API, vendor) without touching your
  config.

## How it works (two phases, daily)

1. **Fetch (your machine, Task Scheduler / cron):** Python collects postings
   from SerpAPI (Google Jobs), LinkedIn (Bright Data dataset), WeWorkRemotely,
   RemoteOK; applies dedup/freshness/relevance filters; writes
   `candidates.json`.
2. **Score + write (Claude, ~30 min later):** candidates are scored against
   your department rubric; kept rows land in your Google Sheet with lead ids,
   risk flags, and reasons. Columns K/L stay manual for your specialists'
   feedback.

## Requirements

- Windows with Python 3.10+ (macOS/Linux: cron variant included), machine on
  at the scheduled hour
- Claude in Chrome extension (sheet writes go through your browser)
- SerpAPI key (own budget), optionally a Bright Data key
- A Google account owning the target sheet
- Gmail connector (optional) for failure alerts

## Costs (order of magnitude)

- SerpAPI: a 250-searches/month plan supports up to 8 queries/day
- Bright Data: billed per LinkedIn record; the wizard keeps inputs lean

Install the plugin, then run **/setup-search-engine** (or just say: "set up
the jobs pipeline for my department").
