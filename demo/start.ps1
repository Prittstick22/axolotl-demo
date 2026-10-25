<#
.SYNOPSIS
  Start the Axolotl demo build on this laptop: one command, safe to run again.

.DESCRIPTION
  Does every step of demo/DEMO_BUILD.md and skips whatever is already done:
    1. checks Docker is running, and that uv and npm are installed;
    2. starts the local MongoDB (Atlas Local in Docker), creating it the first time;
    3. builds the five sandbox images that are missing (all of them with -RebuildImages);
    4. creates .env from demo/demo.env.example if there isn't one;
    5. installs the backend and frontend dependencies;
    6. loads the team's chess data into the local MongoDB if it isn't there yet;
    7. starts the backend and the frontend in the background, logging to demo/.logs/;
    8. waits for both, checks the status chips, and opens the browser.
  Stop it with demo/stop.ps1.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File demo\start.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File demo\start.ps1 -BackendPort 8001 -FrontendPort 5174 -NoBrowser
#>
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [switch]$RebuildImages,
    [switch]$NoBrowser
)

# Not 'Stop': in Windows PowerShell 5.1 that turns a native command's stderr into a fatal
# error, even when redirected, so every failure here is checked through $LASTEXITCODE.
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$Logs = Join-Path $PSScriptRoot '.logs'
$Container = 'axolotl-atlas-local'
$Images = @(
    @{ Tag = 'axolotl-runner:latest'; Args = @('-t', 'axolotl-runner:latest', 'runner/') },
    @{ Tag = 'axolotl-runner:py2.7'; Args = @('-t', 'axolotl-runner:py2.7', '--build-arg', 'PYTHON_VERSION=2.7', '--build-arg', 'PYTEST_VERSION=4.6.11', 'runner/') },
    @{ Tag = 'axolotl-runner:py3.14'; Args = @('-t', 'axolotl-runner:py3.14', '--build-arg', 'PYTHON_VERSION=3.14', '--build-arg', 'PYTEST_VERSION=8.4.2', 'runner/') },
    @{ Tag = 'axolotl-chess-cases:py27'; Args = @('-f', 'runner/Dockerfile.behaviour', '--build-arg', 'PYTHON_IMAGE=python:2.7.18-slim', '-t', 'axolotl-chess-cases:py27', 'runner/') },
    @{ Tag = 'axolotl-chess-cases:py314'; Args = @('-f', 'runner/Dockerfile.behaviour', '--build-arg', 'PYTHON_IMAGE=python:3.14-slim', '-t', 'axolotl-chess-cases:py314', 'runner/') }
)

function Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "ERROR: $text" -ForegroundColor Red; exit 1 }

function Test-Port($port) {
    [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-Http($url, $seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) { return $true }
        } catch { Start-Sleep -Seconds 2 }
    }
    return $false
}

Set-Location $Root

Step 'Checking the tools'
foreach ($tool in 'docker', 'uv', 'npm') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Fail "$tool is not installed or not on PATH. See demo/DEMO_BUILD.md, 'Set up the demo laptop'."
    }
}
docker info --format '{{.ServerVersion}}' *> $null
if ($LASTEXITCODE -ne 0) { Fail 'Docker is installed but not running. Start Docker Desktop, then run this again.' }
foreach ($port in $BackendPort, $FrontendPort) {
    if (Test-Port $port) { Fail "port $port is already in use. Run demo\stop.ps1, or pass -BackendPort / -FrontendPort." }
}

Step "Starting the local MongoDB ($Container)"
$exists = docker ps -a --filter "name=^$Container$" --format '{{.Names}}'
if (-not $exists) {
    docker run -d --name $Container -p 27017:27017 mongodb/mongodb-atlas-local | Out-Null
} else {
    docker start $Container | Out-Null
}
if ($LASTEXITCODE -ne 0) { Fail "could not start the $Container container." }
$deadline = (Get-Date).AddSeconds(180)
do {
    $health = docker inspect --format '{{.State.Health.Status}}' $Container
    if ($health -eq 'healthy') { break }
    Start-Sleep -Seconds 3
} while ((Get-Date) -lt $deadline)
if ($health -ne 'healthy') { Fail "$Container did not become healthy within 3 minutes (status: $health)." }

Step 'Checking the sandbox images'
foreach ($image in $Images) {
    docker image inspect $image.Tag *> $null
    if ($RebuildImages -or $LASTEXITCODE -ne 0) {
        Write-Host "    building $($image.Tag) (a few minutes the first time)"
        docker build -q $image.Args | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "building $($image.Tag) failed." }
    }
}

Step 'Checking .env'
$envFile = Join-Path $Root '.env'
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $PSScriptRoot 'demo.env.example') $envFile
    Write-Host '    created .env from demo/demo.env.example'
}
$envText = Get-Content $envFile -Raw
if ($envText -notmatch '(?m)^ARGON_REPLAY_FILE=\S+') {
    Fail '.env has no ARGON_REPLAY_FILE, so the demo would call Gemini live. Copy the replay lines from demo/demo.env.example.'
}
if ($envText -match '(?m)^MONGODB_URI=mongodb\+srv') {
    Fail '.env points MONGODB_URI at a remote cluster. The demo uses this laptop''s MongoDB: copy MONGODB_URI from demo/demo.env.example.'
}

Step 'Installing the backend dependencies'
Push-Location (Join-Path $Root 'backend')
uv sync -q
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'uv sync failed.' }

Step "Loading the team's chess data (skipped if it's already here)"
uv run python -m app.demo_seed load --if-missing
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'loading the demo data failed (see the message above).' }
Pop-Location

Step 'Installing the frontend dependencies'
Push-Location (Join-Path $Root 'frontend')
if (-not (Test-Path 'node_modules')) {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'npm ci failed.' }
}
Pop-Location

Step "Starting the backend (port $BackendPort) and the frontend (port $FrontendPort)"
New-Item -ItemType Directory -Force $Logs | Out-Null
# Environment overrides beat .env, so the two servers find each other on any ports.
$env:FRONTEND_ORIGIN = "http://localhost:$FrontendPort"
$env:VITE_API_BASE = "http://localhost:$BackendPort/api/v1"
# Through cmd, which writes each server's output to its log. Not Start-Process's own
# -Redirect* options: they make the servers inherit this script's output handles, so
# anything reading the script's output (a pipe, an agent's tool) would wait on the
# servers forever.
$backendLog = Join-Path $Logs 'backend.log'
$frontendLog = Join-Path $Logs 'frontend.log'
Start-Process -FilePath $env:ComSpec -WindowStyle Hidden -WorkingDirectory (Join-Path $Root 'backend') `
    -ArgumentList '/c', "uv run uvicorn app.main:app --port $BackendPort > `"$backendLog`" 2>&1"
Start-Process -FilePath $env:ComSpec -WindowStyle Hidden -WorkingDirectory (Join-Path $Root 'frontend') `
    -ArgumentList '/c', "npm run dev -- --port $FrontendPort --strictPort > `"$frontendLog`" 2>&1"

if (-not (Wait-Http "http://localhost:$BackendPort/api/v1/health" 120)) { Fail "the backend didn't start; see demo\.logs\backend.log" }
if (-not (Wait-Http "http://localhost:$FrontendPort" 120)) { Fail "the frontend didn't start; see demo\.logs\frontend.log" }

Step 'Checking the status chips'
$status = Invoke-RestMethod -Uri "http://localhost:$BackendPort/api/v1/system/status" -TimeoutSec 60
$deadline = (Get-Date).AddSeconds(90)
while (($status.search_indexes.keyword -ne 'ok' -or $status.search_indexes.vector -ne 'ok') -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5   # a new database builds its search indexes once
    $status = Invoke-RestMethod -Uri "http://localhost:$BackendPort/api/v1/system/status" -TimeoutSec 60
}
Write-Host "    MongoDB: $($status.mongodb)   search: $($status.search_indexes.keyword)/$($status.search_indexes.vector)   runner: $($status.runner.available)   model: $($status.gemini.model)"
if ($status.gemini.model -notlike '*replay of*') {
    Write-Host 'WARNING: the model is not a replay, so a migration would call Gemini live. Check ARGON_REPLAY_FILE in .env.' -ForegroundColor Yellow
}

$url = "http://localhost:$FrontendPort/repos/repo_3852f5968630"
Write-Host ''
Write-Host "The demo is running: $url" -ForegroundColor Green
Write-Host '  Plan -> Python 2 to Python 3 -> Create plan -> Approve -> Start migration (about 1.5-2 min, 14/14).'
Write-Host '  Ask (on Search):  "Where is checkmate detected?"   "How is a move like e2e4 parsed?"'
Write-Host "  Logs: demo\.logs\   Stop: powershell -ExecutionPolicy Bypass -File demo\stop.ps1 -BackendPort $BackendPort -FrontendPort $FrontendPort"
if (-not $NoBrowser) { Start-Process $url }
