# OAuth setup for sheet writes (Step 3.4)

Phase 2 refreshes an access token (scope `spreadsheets`) from a refresh token
and calls the Sheets API from the browser. Two artifacts, both in
`profiles/<dept>/`:

- `oauth_client.json` — the OAuth client (id + secret), format
  `{"installed": {"client_id": "...", "client_secret": "..."}}`
- `oauth_token.json` — the refresh token for the Google account owning the
  sheet, minted by `scripts/get_oauth_token.py`

## Path A — client file provided by the pipeline owner (fast)

If the company already runs this pipeline, the owner can share their
`oauth_client.json` (the client identifies the APP, not the account — sharing
it inside the org is normal; the refresh token stays personal).

1. User saves the received file to `profiles/<dept>/oauth_client.json`.
2. On the host: `python scripts/get_oauth_token.py --profile <dept>` — a
   browser opens; approve with the Google account that owns the sheet.
3. Script writes `oauth_token.json`. Done.

## Path B — create their own OAuth client (~10 min, once)

1. https://console.cloud.google.com → create a project (any name).
2. APIs & Services → Library → enable **Google Sheets API**.
3. APIs & Services → OAuth consent screen: user type **Internal** if a
   Workspace org, else External + add the user as a test user.
4. APIs & Services → Credentials → Create credentials → **OAuth client ID** →
   application type **Desktop app** → download JSON.
5. Save the downloaded file as `profiles/<dept>/oauth_client.json`, then run
   Path A step 2.

## Verification & safety

- Both files exist; `oauth_token.json` has a non-empty `refresh_token`.
- NEVER print, log, or echo client_secret / refresh_token into chat, reports,
  or tool output. Existence + shape checks only.
- Token revoked later ("invalid_grant" during Phase 2)? Re-run the mint script
  — see the troubleshoot-pipeline skill.
