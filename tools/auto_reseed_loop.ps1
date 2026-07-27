# HUB full reseed auto-continuation runner (for Windows Task Scheduler)
#
# WHY (Korean context in ASCII to avoid PS cp949 parsing issues):
# After the pagination bug fix (commit 0a1ed45, 2026-07-27) the whole HUB
# dataset (jungong=done/sched, myeolsil=demol) must be re-seeded. One GitHub
# Actions run dies at the 340-min STEP timeout (6h hard cap); its progress is
# committed by the if:always commit step. So several rounds are needed to
# finish. A Claude session's background shell dies with the session, breaking
# the chain -- this script, registered in Task Scheduler, keeps the rounds
# going independently of any session.
#
# BEHAVIOR (intended trigger: every 30 min):
#   1) If the latest update-hub run is still in_progress -> do nothing
#      (prevents duplicate dispatch).
#   2) Otherwise read progress from origin: meta.scanned / meta.scanned_demol.
#   3) scanned   < 148 -> dispatch mode=full
#      scanned  == 148 and scanned_demol < 148 -> dispatch mode=demol
#      both     == 148 -> log completion (unregister the task manually).
#
# Register:
#   $A = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\Users\shpar\OneDrive\문서\Claude\aptweather\tools\auto_reseed_loop.ps1"'
#   $T = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 30)
#   Register-ScheduledTask -TaskName 'aptweather HUB reseed auto' -Action $A -Trigger $T
# Unregister:
#   Unregister-ScheduledTask -TaskName 'aptweather HUB reseed auto' -Confirm:$false

$ErrorActionPreference = 'Stop'
$Repo = 'WatermelonPark/aptweather'
$Target = 148
# NOTE: the repo path contains a Korean folder name. Writing it as a literal
# breaks when PowerShell reads this file as cp949, so build it from the script's
# own location instead (this file lives in <repo>\tools\).
$RepoDir = Split-Path -Parent $PSScriptRoot
$LogFile = Join-Path $RepoDir 'tools\data\auto_reseed_log.txt'

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $LogFile -Value $line -Encoding utf8
}

Set-Location $RepoDir

# GitHub token from git credential helper (same one git push already uses).
# NOTE: piping a here-string into `git credential fill` mangles the blank-line
# terminator in PowerShell ("refusing to work with credential missing protocol
# field"), so write a temp input file and feed it via cmd redirection instead.
$credIn = [System.IO.Path]::GetTempFileName()
"protocol=https`nhost=github.com`n" | Out-File -FilePath $credIn -Encoding ascii -NoNewline
$cred = & cmd /c "git credential fill < `"$credIn`"" 2>$null
Remove-Item $credIn -ErrorAction SilentlyContinue
$pwLine = $cred | Select-String '^password='
if (-not $pwLine) { Write-Log 'ERROR: failed to get GitHub token'; exit 1 }
$token = $pwLine.ToString() -replace '^password=', ''

$headers = @{ Authorization = "token $token"; Accept = 'application/vnd.github+json' }

# 1) skip if a run is still going
$runs = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/actions/workflows/update-hub.yml/runs?per_page=1" -Headers $headers
$latest = $runs.workflow_runs[0]
if ($latest.status -ne 'completed') {
    Write-Log ("run {0} still {1} -- waiting" -f $latest.id, $latest.status)
    exit 0
}

# 2) read progress from origin
git fetch origin --quiet 2>$null
$json = git show origin/main:tools/data/hub_permits.json 2>$null | Out-String
$data = $json | ConvertFrom-Json
$scanned = @($data.meta.scanned).Count
$scannedDemol = @($data.meta.scanned_demol).Count

# 3) decide next round
if ($scanned -lt $Target) {
    $mode = 'full'
} elseif ($scannedDemol -lt $Target) {
    $mode = 'demol'
} else {
    # Both done -- self-unregister so the task stops firing on its own.
    Write-Log ("DONE: jungong {0}/{1}, myeolsil {2}/{1} -- self-unregistering task" -f $scanned, $Target, $scannedDemol)
    try {
        Unregister-ScheduledTask -TaskName 'aptweather HUB reseed auto' -Confirm:$false
        Write-Log 'task unregistered'
    } catch {
        Write-Log ("unregister failed: {0}" -f $_.Exception.Message)
    }
    exit 0
}

# Stall detection: if the last round produced no progress, note it in the log.
# (Common cause: data.go.kr daily quota exhausted -- the collector retries then
# skips groups without saving, so the run burns time without advancing. Not an
# error; the next round picks those groups up once quota resets. We keep
# dispatching regardless, just make the stall visible.)
$prevFile = Join-Path $RepoDir 'tools\data\auto_reseed_prev.txt'
$cur = "$scanned/$scannedDemol"
if (Test-Path $prevFile) {
    $prev = (Get-Content $prevFile -Raw).Trim()
    if ($prev -eq $cur) {
        Write-Log ("STALL: no progress since last round ({0}) -- likely API quota; continuing anyway" -f $cur)
    }
}
Set-Content -Path $prevFile -Value $cur -Encoding ascii

$body = @{ ref = 'main'; inputs = @{ mode = $mode } } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$Repo/actions/workflows/update-hub.yml/dispatches" -Headers $headers -Body $body | Out-Null
Write-Log ("dispatch mode={0} (jungong {1}/{2}, myeolsil {3}/{2})" -f $mode, $scanned, $Target, $scannedDemol)
