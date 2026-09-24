$ErrorActionPreference = 'Stop'
$plannerRoot = $PSScriptRoot
$plannerRuntime = Join-Path $plannerRoot '.runtime'
New-Item -ItemType Directory -Force -Path $plannerRuntime | Out-Null
$plannerPython = Join-Path $plannerRuntime 'venv\Scripts\python.exe'
$workspacePython = Join-Path $plannerRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $workspacePython)) { $workspacePython = Join-Path $plannerRoot '..\..\.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $plannerPython)) {
    if (Test-Path -LiteralPath $workspacePython) { $plannerPython = (Resolve-Path -LiteralPath $workspacePython).Path }
    else {
        python -m venv (Join-Path $plannerRuntime 'venv')
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11-3.13 and retry.' }
    }
    & $plannerPython -m pip install -r (Join-Path $plannerRoot 'backend\requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
}
$plannerFrontend = Join-Path $plannerRoot 'frontend'
if (-not (Test-Path -LiteralPath (Join-Path $plannerFrontend 'node_modules'))) {
    Push-Location -LiteralPath $plannerFrontend
    try { npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' } } finally { Pop-Location }
}
# Windows user-protected local credential; excluded from source bundles.
$plannerTrafficSecret = Join-Path $plannerRuntime 'tomtom-key.dpapi'
if (-not $env:TOMTOM_API_KEY -and (Test-Path -LiteralPath $plannerTrafficSecret)) {
    $plannerSecureKey = (Get-Content -LiteralPath $plannerTrafficSecret -Raw).Trim() | ConvertTo-SecureString
    $env:TOMTOM_API_KEY = [System.Net.NetworkCredential]::new('', $plannerSecureKey).Password
}
$env:DATA_DIR = Join-Path $plannerRoot 'data\raw'
$env:STORE_DIR = Join-Path $plannerRoot 'backend\store'
$env:VITE_API_BASE = '/api'
if (-not (Get-NetTCPConnection -LocalPort 8004 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $plannerPython -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8004') -WorkingDirectory (Join-Path $plannerRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $plannerRuntime 'backend.log') -RedirectStandardError (Join-Path $plannerRuntime 'backend-error.log') | Out-Null
} else { Write-Host 'Port 8004 is already running; leaving that process in place.' }
if (-not (Get-NetTCPConnection -LocalPort 5176 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-Command','& npm.cmd run dev -- --host 127.0.0.1 --port 5176 --strictPort') -WorkingDirectory $plannerFrontend -WindowStyle Hidden -RedirectStandardOutput (Join-Path $plannerRuntime 'frontend.log') -RedirectStandardError (Join-Path $plannerRuntime 'frontend-error.log') | Out-Null
} else { Write-Host 'Port 5176 is already running; leaving that process in place.' }
Write-Host 'Open http://127.0.0.1:5176/ once both services are ready.'

