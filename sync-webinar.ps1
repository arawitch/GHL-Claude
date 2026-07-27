# Scheduled WebinarJam -> GoHighLevel sync.
#
# Mirrors registrations, attendance, replay views and purchases into GHL tags.
# Replaces the webhook entirely: the API is the source of truth, and a sync is
# idempotent, so a run that fails is repaired by the next one rather than
# leaving a permanent hole.
#
# Run it from Task Scheduler. Twice daily is plenty for a weekly webinar;
# hourly on the day itself if you want attendance to land promptly.
#
#   powershell -ExecutionPolicy Bypass -File C:\Users\audry\GHL-Claude\sync-webinar.ps1

$ErrorActionPreference = 'Stop'

$Root       = Split-Path -Parent $MyInvocation.MyCommand.Path
$WebinarId  = 53          # Options Live Webinar - weekly Thursday series
$StayedMins = 30          # tag '<date> stayed' past this many minutes watched
$WindowDays = 7           # sync sessions within this many days either side
$LogDir     = Join-Path $Root 'logs'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$log   = Join-Path $LogDir "sync-$stamp.log"

function Write-Log($msg) {
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
  Write-Host $line
  Add-Content -Path $log -Value $line
}

# Credentials come from the user environment, never from this file.
foreach ($v in @('GHL_API_KEY','GHL_LOCATION_ID','WEBINARJAM_API_KEY')) {
  if (-not (Get-Item "env:$v" -ErrorAction SilentlyContinue)) {
    Write-Log "MISSING ENVIRONMENT VARIABLE: $v - aborting"
    exit 1
  }
}

# The SMS sub-account is optional. If both values are present the sync tags
# there too; if not, it silently stays single-location rather than failing.
if ($env:GHL_SMS_API_KEY -and $env:GHL_SMS_LOCATION_ID) {
  Write-Log "SMS sub-account configured ($env:GHL_SMS_LOCATION_ID)"
} else {
  Write-Log 'SMS sub-account not configured - tagging the main location only'
}

$py = $null
foreach ($c in @('python','py','python3')) {
  try { if (& $c --version 2>$null) { $py = $c; break } } catch {}
}
if (-not $py) { Write-Log 'Python not found - aborting'; exit 1 }

Set-Location $Root
Write-Log "starting sync (webinar $WebinarId, window $WindowDays days)"

$output = & $py cli.py sync-webinar --webinar-id $WebinarId --auto `
            --window-days $WindowDays --stayed-minutes $StayedMins --apply 2>&1
$output | ForEach-Object { Write-Log $_ }

if ($LASTEXITCODE -ne 0) {
  Write-Log "SYNC FAILED with exit code $LASTEXITCODE"
  exit $LASTEXITCODE
}

# A shortfall that survives the reconciliation recheck means GHL is missing
# contacts WebinarJam has. Worth surfacing rather than burying in the log.
if ($output -match 'SHORTFALL') {
  Write-Log 'WARNING: reconciliation reported a shortfall - check the log above'
}

# The one-click registration link points at a specific session number. When the
# configured sessions run out the link silently stops working, so warn early.
if ($output -match 'no session within') {
  Write-Log 'WARNING: no upcoming session found - extend the webinar series in WebinarJam'
}

Write-Log 'done'

# Keep the log directory from growing without bound.
Get-ChildItem $LogDir -Filter 'sync-*.log' |
  Sort-Object LastWriteTime -Descending |
  Select-Object -Skip 60 |
  Remove-Item -Force -ErrorAction SilentlyContinue
