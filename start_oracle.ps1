# Oracle Discord Bot Startup Script (PowerShell)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "          🔮 Starting Oracle Discord Bot             " -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan

$PythonExe = if (Test-Path "$ScriptDir\.venv\Scripts\python.exe") {
    "$ScriptDir\.venv\Scripts\python.exe"
} elseif (Test-Path "$ScriptDir\.venv\bin\python") {
    "$ScriptDir\.venv\bin\python"
} else {
    "python"
}

Write-Host "Using Python: $PythonExe" -ForegroundColor Green
& $PythonExe "$ScriptDir\scripts\oracle_bot.py"

if ($LASTEXITCODE -ne 0) {
    Write-Host "`nOracle exited with error code $LASTEXITCODE." -ForegroundColor Red
}
