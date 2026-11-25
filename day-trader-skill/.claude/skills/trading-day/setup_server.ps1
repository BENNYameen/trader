# Registers both daily paper-trading runs on THIS machine (for a server that is on every day):
#   PaperTradingDay  09:10 India time  India stocks + NIFTY/SENSEX options   (run_day.py run)
#   PaperTradingUS   19:45 India time  US stocks, original repo code         (day-trader-us autopilot)
# The India times are converted to this machine's own time zone, so the server can keep any zone.
# The tasks fire every day; the code itself skips weekends and market holidays (India and US).
#
# Run it once in PowerShell on the server (as Administrator if you can: then the runs also work while
# you are signed out; otherwise only disconnect from the remote desktop, never sign out):
#   powershell -ExecutionPolicy Bypass -File ".\setup_server.ps1"
# Remove both tasks:   powershell -ExecutionPolicy Bypass -File ".\setup_server.ps1" -Remove
# If this machine's time zone moves its clocks (daylight saving), run it again after the change.
param([switch]$Remove)
$ErrorActionPreference = "Stop"

$repo    = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$trading = Split-Path $repo -Parent
$us      = Join-Path $trading "day-trader-us"
$opt     = Join-Path $trading "options-ensemble"
$names   = @("PaperTradingDay", "PaperTradingUS")

if ($Remove) {
    foreach ($n in $names) { Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue }
    "Removed both tasks."
    return
}
foreach ($p in @($opt, $us)) {
    if (-not (Test-Path $p)) { throw "Missing $p - the three folders must sit side by side in one 'trading' folder." }
}
if ($trading -match "OneDrive") {
    Write-Warning "This copy is inside OneDrive. If another machine syncs the same folder, the two will fight over the live files. Prefer a folder like C:\trading."
}

# Python: ask Python itself where it lives (python.org install or the py launcher)
function Find-Python {
    $ErrorActionPreference = "Continue"          # a missing python writes to stderr; that must not stop us
    foreach ($try in @("python", "py")) {
        if (-not (Get-Command $try -ErrorAction SilentlyContinue)) { continue }
        try {
            if ($try -eq "py") { $o = & py -3 -c "import sys; print(sys.executable)" 2>$null }
            else { $o = & python -c "import sys; print(sys.executable)" 2>$null }
            if ($LASTEXITCODE -eq 0 -and $o) { return ($o | Select-Object -First 1).Trim() }
        } catch { }
    }
    return $null
}
$exe = Find-Python
if (-not $exe) { throw "Python 3 not found. Install it from python.org (tick 'Add python.exe to PATH'), then run this again." }
$pyw = Join-Path (Split-Path $exe) "pythonw.exe"          # no console window
if (-not (Test-Path $pyw)) { $pyw = $exe }

# India time -> this machine's time
$ist = [System.TimeZoneInfo]::FindSystemTimeZoneById("India Standard Time")
function Get-LocalFromIst([int]$h, [int]$m) {
    $d = [DateTime]::UtcNow
    $t = New-Object DateTime ($d.Year, $d.Month, $d.Day, $h, $m, 0)          # Kind Unspecified
    return [System.TimeZoneInfo]::ConvertTime($t, $ist, [System.TimeZoneInfo]::Local)
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
$user = "$env:USERDOMAIN\$env:USERNAME"
$logon = if ($isAdmin) { "S4U" } else { "Interactive" }     # S4U: runs whether you are signed in or not
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType $logon -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
            -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 8) -MultipleInstances IgnoreNew

$jobs = @(
    @{ Name = "PaperTradingDay"; H = 9;  M = 10; Script = (Join-Path $PSScriptRoot "run_day.py"); Dir = $repo;
       End = "2026-12-19T00:00:00"; What = "India stocks + NIFTY/SENSEX options, paper only" },
    @{ Name = "PaperTradingUS";  H = 19; M = 45; Script = (Join-Path $us "autopilot\us_auto.py"); Dir = $us;
       End = "2026-12-26T00:00:00"; What = "US stocks, original day-trader-skill code, paper only" }
)
foreach ($j in $jobs) {
    $at = Get-LocalFromIst $j.H $j.M
    $action  = New-ScheduledTaskAction -Execute $pyw -Argument ('"' + $j.Script + '" run') -WorkingDirectory $j.Dir
    $trigger = New-ScheduledTaskTrigger -Daily -At $at
    $trigger.EndBoundary = $j.End
    Register-ScheduledTask -TaskName $j.Name -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Force -Description ("Paper trading month: " + $j.What + ".") | Out-Null
    $info = Get-ScheduledTaskInfo -TaskName $j.Name
    "{0}: {1:D2}:{2:D2} India time = {3:HH:mm} here; next run {4}" -f $j.Name, $j.H, $j.M, $at, $info.NextRunTime
}
""
"Python: $pyw"
if ($isAdmin) { "The runs work even while you are signed out." }
else { "Not run as Administrator: the runs work while you are signed in. Disconnect from the remote desktop, do not sign out." }
"Next: python `"$PSScriptRoot\move_to_server.py`" check"
