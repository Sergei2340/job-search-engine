# Scheduling (Step 7)

## Slot rules

- Phase 1 at `HH:00`, Phase 2 at `HH:30` (LinkedIn snapshot + company-size
  enrichment can take up to ~20 min to build; 30 min is safe).
- If ANY other job-search pipeline runs on the same machine or shares an API
  key / Google account, keep a FULL HOUR between pipelines (e.g. 07:00, 08:00,
  09:00 …). Ask; don't assume.
- The Claude desktop app must be open at HH:30 (Cowork tasks fire only while
  the app runs; a missed task fires on next launch).

## Phase 1 — Windows Task Scheduler

Generate with the user's hour and working folder substituted; they run it in
PowerShell (same Windows user that owns `.env` / OAuth files):

```powershell
$Action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument '-ExecutionPolicy Bypass -NoProfile -File "<WORKING_FOLDER>\engine\run_fetch.ps1" -ProfileName <dept>'
$Trigger = New-ScheduledTaskTrigger -Daily -At <H>:00AM
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "<dept> Jobs Fetch" -Action $Action -Trigger $Trigger `
  -Principal $Principal -Description "<dept> lead-gen Phase 1 fetch (daily, job-search-engine)."
```

Immediately test:

```powershell
Start-ScheduledTask -TaskName "<dept> Jobs Fetch"
```

Verify: a fresh `profiles/<dept>/logs/fetch_*.log` appears in the working
folder and ends with `Exit: 0`. (`run_fetch.ps1` finds Python, installs
requirements, runs the fetch, prunes logs older than 14 days.)

macOS/Linux instead: `crontab -e` →
`0 <H> * * * cd <WORKING_FOLDER> && python3 -m engine.main --profile <dept> >> profiles/<dept>/logs/fetch_$(date +\%F).log 2>&1`

## Phase 2 — Cowork scheduled task

Create a scheduled task named `<dept>-jobs-pipeline`, cron `30 <H> * * *`,
prompt:

> Run the job-search-engine `run-pipeline` skill for profile `<dept>`.
> Working folder: <WORKING_FOLDER>.

After creating it, instruct the user to open the Scheduled sidebar and click
**Run now** once — this pre-approves the tools the task needs (Chrome for the
Sheets write, Gmail for alerts) so unattended runs never stall on permission
prompts. It is fine that this immediate run finds no fresh candidates.
