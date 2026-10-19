# K Terminal: build and start everything with Docker (Windows).
#
# In PowerShell, from the terminal folder:
#   powershell -ExecutionPolicy Bypass -File .\start.ps1
#
# First run: creates secrets, builds, starts and offers to create your login.
# Later runs: rebuild what changed and restart; data is kept.
# Stop with:  docker compose --project-directory deploy -f deploy/docker-compose.yml stop
# Step-by-step guide: docs/18-quick-start.md. (ASCII only: Windows PowerShell 5.1
# reads scripts without a byte-order mark in the legacy code page.)

# Not 'Stop': Windows PowerShell 5.1 turns redirected stderr of native commands
# (docker) into errors, which 'Stop' would make fatal. Exit codes are checked instead.
$ErrorActionPreference = 'Continue'
Set-Location -Path $PSScriptRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host 'Docker is not installed. Install Docker Desktop: https://www.docker.com/products/docker-desktop/' -ForegroundColor Red
    exit 1
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Docker is not running. Start Docker Desktop, wait until it says it is running, then run this again.' -ForegroundColor Red
    exit 1
}

# Secrets live only on this machine (deploy/secrets is never committed). Written as
# plain ASCII without a byte-order mark or newline.
$secrets = Join-Path $PSScriptRoot 'deploy/secrets'
New-Item -ItemType Directory -Force -Path $secrets -ErrorAction Stop | Out-Null
function New-Secret([string]$name) {
    $file = Join-Path $secrets $name
    if (-not (Test-Path $file)) {
        $bytes = New-Object byte[] 32
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $value = -join ($bytes | ForEach-Object { $_.ToString('x2') })
        [IO.File]::WriteAllText($file, $value)
        Write-Host "created deploy\secrets\$name"
    }
}
New-Secret 'postgres_password'
New-Secret 'session_secret'
$oanda = Join-Path $secrets 'oanda_token'
if (-not (Test-Path $oanda)) {
    [IO.File]::WriteAllText($oanda, '')
    Write-Host 'created deploy\secrets\oanda_token (empty: paste your OANDA token into it to trade FX, gold and indices)'
}

$compose = @('compose', '--project-directory', 'deploy')
if (Test-Path (Join-Path $PSScriptRoot '.env')) { $compose += @('--env-file', '.env') }
$compose += @('-f', 'deploy/docker-compose.yml')

Write-Host 'Building and starting (the first time takes a few minutes)...'
& docker @compose up -d --build
if ($LASTEXITCODE -ne 0) { Write-Host 'Starting failed (see the messages above).' -ForegroundColor Red; exit 1 }

Write-Host 'Waiting for the terminal to answer...'
$ready = $false
$probe = "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"
for ($i = 0; $i -lt 90; $i++) {
    $null | & docker @compose exec -T api python -c $probe *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    Write-Host 'The terminal did not become ready. Its logs:' -ForegroundColor Red
    & docker @compose logs --tail=40 api migrate
    exit 1
}

$users = ($null | & docker @compose exec -T api kterminal users list 2>$null) -join "`n"
if ($users -match '(?m)^no users yet') {
    Write-Host ''
    Write-Host 'Create your dashboard login (password: at least 12 characters).'
    $username = Read-Host "Username (a-z, 0-9, '.', '_', '-')"
    if ($username) {
        & docker @compose exec api kterminal users add $username --role ADMIN
    }
}

Write-Host ''
Write-Host 'K Terminal is running: open https://localhost in your browser.' -ForegroundColor Green
Write-Host 'Your browser will warn about the certificate the first time (it is made on this'
Write-Host 'computer): choose Advanced, then continue to localhost.'
