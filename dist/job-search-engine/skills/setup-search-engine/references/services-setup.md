# External services setup (Step 3)

Collect keys into `profiles/<dept>/.env` (create from this template; never
echo values back into chat):

```
SERPAPI_KEY=
BRIGHTDATA_API_KEY=
SHEET_URL=
```

## SerpAPI (Google Jobs) — required for the primary volume source

1. https://serpapi.com → register → pick a plan. The pipeline's math: a
   250-searches/month plan supports **at most 8 queries per daily run**
   (8 × 31 = 248). Size `sources.serpapi.queries` in profile.yaml to the plan.
2. Key: Dashboard → "Api key".
3. One key per department — a shared key means one department's queries starve
   another's budget mid-month.

## Bright Data (LinkedIn) — optional, strongly recommended

LinkedIn is typically the richest source of agency/contract leads (the
score-5 kind) and the only reliable DACH coverage.

1. https://brightdata.com → account → API key (Account settings → API tokens).
2. Subscribe to the Web Scraper API dataset **"LinkedIn job listings
   information — discover by keyword"** (dataset id `gd_lpfll7v5hcqtkxl6l`,
   already the engine default).
3. Billing is per record returned; the profile's `inputs` list and
   `time_range: "Past 24 hours"` are the cost levers. Start with ≤ 10 inputs.
4. The jobs source triggers at most once per UTC day per profile
   (`run_once_per_day`), and a poll timeout never re-charges the day.
5. For the Headcount column, also subscribe to **"LinkedIn companies —
   collect by URL"** (dataset id `gd_l1vikfnt1wgvvqz95w`). Company-size
   lookups are $1.5/1K records with 5K/month free; results are cached in
   `state/company_size_cache.json`, so each company is looked up roughly once
   ever. A poll timeout here doesn't re-charge either: the snapshot id is
   journaled and recovered next run. NOTE the free tier and the key are
   per-Bright-Data-account — several departments sharing one account share the
   5K/month pool (and a company can be billed once per department unless they
   point `COMPANY_SIZE_CACHE_FILE` at a shared cache).

## Google Sheet — required

1. User creates a new spreadsheet in the Google account they are signed into
   in Chrome; names it e.g. `<Dept> Jobs Automated Search`.
2. Paste the exact header row from `sheet-template.md` into A1:Q1.
3. User pastes the sheet URL into chat → extract the id between `/d/` and the
   next `/` → `sheet.spreadsheet_id` in profile.yaml; tab name (default
   `Sheet1`) → `sheet.tab`. Save the URL to `.env` `SHEET_URL` for reference.

## OAuth for sheet writes — required

See `oauth-setup.md`. End state: `profiles/<dept>/oauth_client.json` and
`profiles/<dept>/oauth_token.json` both exist. Verify by file existence and by
the JSON shape (`installed.client_id` / `refresh_token`), NOT by printing
contents.
