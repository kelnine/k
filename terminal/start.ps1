# K Terminal: build and start everything with Docker (Windows).
#
# In PowerShell, from the terminal folder:
#   powershell -ExecutionPolicy Bypass -File .\start.ps1           # start (or restart)
#   powershell -ExecutionPolicy Bypass -File .\start.ps1 -Login    # only create a dashboard login
#
# First run: creates secrets, builds, starts and asks for your login.
# Later runs: rebuild what changed and restart; data is kept.
# Run without a keyboard (by an assistant or a scheduler), it never waits for input:
# a missing login is created in a new PowerShell window that opens for you.
# Stop with:  docker compose --project-directory deploy -f deploy/docker-compose.yml stop
# Step-by-step guide: docs/18-quick-start.md. (ASCII only: Windows PowerShell 5.1
# reads scripts without a byte-order mark in the legacy code page.)
param([switch]$Login)

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

$compose = @('compose', '--project-directory', 'deploy')
if (Test-Path (Join-Path $PSScriptRoot '.env')) { $compose += @('--env-file', '.env') }
$compose += @('-f', 'deploy/docker-compose.yml')

function Test-Interactive {
    if (-not [Environment]::UserInteractive) { return $false }
    if ([Console]::IsInputRedirected) { return $false }
    foreach ($arg in [Environment]::GetCommandLineArgs()) {
        if ($arg -like '-noni*') { return $false }
    }
    return $true
}

function Get-UsersList {
    return (($null | & docker @compose exec -T api kterminal users list 2>$null) -join "`n")
}

# Ask for the username here (checked before anything runs in Docker), then `users add`
# asks for the password twice. Only the password is asked again after a rejection:
# a prompt after an interactive `docker compose exec` may read a disturbed console.
function New-Login {
    $username = ''
    while ($true) {
        Write-Host ''
        Write-Host 'Create your dashboard login.'
        try { $username = Read-Host "Username (3-32 characters: a letter first, then letters, digits, '.', '_' or '-')" } catch { $username = '' }
        $username = ([string]$username).Trim().ToLowerInvariant()
        if (-not $username) {
            Write-Host 'No login created. Create one later with: powershell -ExecutionPolicy Bypass -File .\start.ps1 -Login'
            return
        }
        if ($username -cmatch '^[a-z][a-z0-9_.-]{2,31}$') { break }
        Write-Host 'That username is not allowed.'
    }
    Write-Host 'Now choose a password of at least 12 characters (asked twice; nothing shows while you type).'
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        & docker @compose exec api kterminal users add $username --role ADMIN
        if ($LASTEXITCODE -eq 0) { return }
    }
    Write-Host 'No login created. Try again with: powershell -ExecutionPolicy Bypass -File .\start.ps1 -Login'
}

if ($Login) {
    $null | & docker @compose exec -T api true *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'The terminal is not running. Start it first: powershell -ExecutionPolicy Bypass -File .\start.ps1' -ForegroundColor Red
        exit 1
    }
    New-Login
    exit 0
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

Write-Host 'Building and starting (the first time takes a few minutes)...'
$null | & docker @compose up -d --build
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

$users = Get-UsersList
if ($users -match '(?m)^sign-in: off') {
    Write-Host 'No login needed: the dashboard opens directly on this computer.'
} elseif ($users -match '(?m)^no users yet') {
    if (Test-Interactive) {
        New-Login
    } elseif ($env:OS -eq 'Windows_NT') {
        # No keyboard here: the person types their own username and password in a
        # window of their own (never through whoever runs this script).
        $shell = (Get-Process -Id $PID).Path
        Start-Process -FilePath $shell -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Login')
        Write-Host 'No dashboard login yet: a PowerShell window has opened to create it.'
    } else {
        Write-Host 'No dashboard login yet. In a terminal window, in this folder, run: pwsh -File ./start.ps1 -Login'
    }
}

Write-Host ''
Write-Host 'K Terminal is running: open https://localhost in your browser.' -ForegroundColor Green
Write-Host 'Your browser will warn about the certificate the first time (it is made on this'
Write-Host 'computer): choose Advanced, then continue to localhost.'
