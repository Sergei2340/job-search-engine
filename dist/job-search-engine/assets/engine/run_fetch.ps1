# job-search-engine - Phase 1 fetch runner (Windows), department-agnostic.
# Registered once per department in Task Scheduler:
#   powershell -ExecutionPolicy Bypass -NoProfile -File engine\run_fetch.ps1 -ProfileName <dept>
# Writes profiles/<dept>/candidates.json for the Cowork Phase 2 task to consume.
# Logs to profiles/<dept>/logs/fetch_<date>.log, prunes logs older than 14 days.
#
# Pure ASCII only. PowerShell 5.1 on Windows 10 reads unmarked .ps1 files as
# Windows-1252; non-ASCII chars break string literals.

param(
    [Parameter(Mandatory = $true)][string]$ProfileName,
    [int]$MaxAge = 24
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot  = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

$ProfileDir = Join-Path (Join-Path $RepoRoot "profiles") $ProfileName
if (-not (Test-Path (Join-Path $ProfileDir "profile.yaml"))) {
    Write-Host "ERROR: no profile.yaml in $ProfileDir"
    exit 2
}

$LogDir = Join-Path $ProfileDir "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}
$LogFile = Join-Path $LogDir ("fetch_{0:yyyy-MM-dd_HH-mm}.log" -f (Get-Date))

function Log($msg) {
    $line = if ($msg -is [string]) { $msg } else { ($msg | Out-String).TrimEnd() }
    Add-Content -Path $LogFile -Value $line
    Write-Host $line
}

Log "=== job-search-engine fetch [$ProfileName] - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz') ==="
Log "RepoRoot: $RepoRoot"
Log "User:     $env:USERNAME"

# Find a Python interpreter. Task Scheduler non-interactive sessions can have a
# narrower PATH than interactive shells, so look in well-known locations too.
$pythonCandidates = @(
    (Get-Command py     -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "C:\Windows\py.exe",
    "C:\Windows\System32\py.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

if (-not $pythonCandidates) {
    Log "ERROR: no Python interpreter found on PATH or in well-known locations."
    Log "=== Exit: 2 ==="
    exit 2
}

$Python = $pythonCandidates[0]
Log "Python: $Python"

try {
    Log "--- pip install -r requirements.txt ---"
    & $Python -m pip install -r (Join-Path $RepoRoot "requirements.txt") --disable-pip-version-check 2>&1 |
        ForEach-Object { Log $_ }
    Log "pip exit: $LASTEXITCODE"

    Log "--- python -m engine.main --profile $ProfileName --max-age $MaxAge ---"
    & $Python -m engine.main --profile $ProfileName --max-age $MaxAge 2>&1 | ForEach-Object { Log $_ }
    $exit = $LASTEXITCODE
    Log "main exit: $exit"
    Log "=== Exit: $exit ==="
}
catch {
    Log "EXCEPTION: $($_.Exception.Message)"
    Log "=== Exit: 3 ==="
    exit 3
}

# Prune logs older than 14 days.
Get-ChildItem -Path $LogDir -Filter "fetch_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

exit $exit
