# Environment checks (Step 1)

Run all four; report a compact pass/fail table to the user before moving on.

## 1. Claude in Chrome extension (REQUIRED)

Phase 2 writes to Google Sheets via a browser JS fetch from a docs.google.com
tab — no extension, no writes.

- Check: call the Chrome tabs-listing tool (load Chrome tools via ToolSearch
  if deferred). Success = a browser context is returned.
- Fail → user installs the extension: https://claude.ai/chrome, signs into
  Chrome with the profile they normally use, restarts the browser. Re-check.
- Also confirm the user is signed into the Google account that will own the
  sheet in that same Chrome profile.

## 2. Python 3.10+ on the host (REQUIRED)

The sandbox is NOT the host — never claim Python is present from a sandbox
check. Ask the user to run in their terminal:

```
python --version
```

Accept 3.10+. If missing → https://www.python.org/downloads/ (check "Add
python.exe to PATH" during install on Windows), then re-verify.

## 3. Always-on machine at the chosen hour (REQUIRED)

Task Scheduler fires only if the machine is on (task is configured to run on
next wake if missed, but chronic misses starve the pipeline). Cowork Phase 2
fires only while the Claude desktop app is running. State plainly: "your
machine and the Claude app need to be on around HH:00–HH:45 daily."

## 4. Alert connectors (OPTIONAL)

Blocked-write alerts use Gmail (+ Google Calendar fallback). Check tool
availability; if the user has no Gmail connector, offer to set it up in
Settings → Connectors, or continue with report-only alerts and say so in the
final recap.

## Non-Windows hosts

The runner and scheduling docs assume Windows (Task Scheduler + PowerShell).
On macOS/Linux, Phase 1 is the same Python command — schedule via cron:
`0 <hour> * * * cd <working folder> && python3 -m engine.main --profile <dept>`
— and skip run_fetch.ps1. Log by redirecting output. Phase 2 is identical.
