# Run from the repository root after adding ODOO_ONLINE_URL and ODOO_ONLINE_API_KEY
# to the ignored local .env. Odoo Online is read only; app writes use a separate DB.
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$Port = 8005,
    [switch]$WithOllama,
    [string]$Model = 'qwen3:4b'
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repo

function Check-Exit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step thất bại (mã $LASTEXITCODE)." }
}

foreach ($name in @('docker', 'python', 'npm.cmd')) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { throw "Thiếu $name trên máy." }
}

$localEnv = Join-Path $repo '.env'
if (-not (Test-Path $localEnv)) { throw 'Chưa có .env local. Xem mục Odoo Online trong README.' }
$allowed = @('APP_DB_PASSWORD', 'DEMO_PASSWORD', 'JWT_SECRET', 'AS_OF_DATE',
             'ODOO_ONLINE_URL', 'ODOO_ONLINE_API_KEY', 'ODOO_ONLINE_DB', 'ODOO_ONLINE_DISPUTE_FIELD')
foreach ($line in [System.IO.File]::ReadAllLines($localEnv)) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $key = $Matches[1]
        if ($key -in $allowed) {
            [Environment]::SetEnvironmentVariable($key, $Matches[2].Trim().Trim('"').Trim("'"), 'Process')
        }
    }
}
if (-not $env:ODOO_ONLINE_URL -or -not $env:ODOO_ONLINE_API_KEY) {
    throw 'Thêm ODOO_ONLINE_URL và ODOO_ONLINE_API_KEY vào .env local. Không ghi API key vào .env.example hoặc Git.'
}
if (-not $env:APP_DB_PASSWORD -or -not $env:DEMO_PASSWORD -or -not $env:JWT_SECRET) {
    throw '.env cần APP_DB_PASSWORD, DEMO_PASSWORD và JWT_SECRET như bản demo local.'
}

$env:ODOO_SOURCE = 'online'
$env:APP_DB_NAME = 'thutien_online'
$env:APP_DB_USER = 'thutien_app'
$env:APP_DB_HOST = '127.0.0.1'
$env:OLLAMA_ENABLED = if ($WithOllama) { '1' } else { '0' }
if ($WithOllama) {
    $compose = @('compose', '-f', 'docker-compose.yml', '-f', 'docker-compose.ollama.yml')
    & docker @compose up -d db ollama
    $env:OLLAMA_URL = 'http://127.0.0.1:11435'
    $env:OLLAMA_MODEL = $Model
    $env:OLLAMA_TIMEOUT_SECONDS = '60'
} else {
    $compose = @('compose', '-f', 'docker-compose.yml')
    & docker @compose up -d db
}
Check-Exit 'Khởi động PostgreSQL'

$portLine = & docker @compose port db 5432
Check-Exit 'Đọc cổng PostgreSQL'
$portMatch = [regex]::Match(($portLine -join ' '), ':(\d+)\s*$')
if (-not $portMatch.Success) { throw 'Không đọc được cổng PostgreSQL.' }
$env:APP_DB_PORT = $portMatch.Groups[1].Value

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    & docker @compose exec -T db pg_isready -U odoo -d postgres 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw 'PostgreSQL chưa sẵn sàng.' }

function Pg-Value([string]$Sql) {
    $result = & docker @compose exec -T db psql -U odoo -d postgres -Atqc $Sql
    Check-Exit 'Kiểm tra PostgreSQL'
    return ($result -join '').Trim()
}

if ((Pg-Value "SELECT 1 FROM pg_roles WHERE rolname='thutien_app'") -ne '1') {
    Get-Content 'scripts/init_app_db.sql' -Raw -Encoding UTF8 |
        & docker @compose exec -T db psql -v ON_ERROR_STOP=1 -U odoo -d postgres
    Check-Exit 'Khởi tạo tài khoản ứng dụng'
}
if ((Pg-Value "SELECT 1 FROM pg_database WHERE datname='thutien_online'") -ne '1') {
    & docker @compose exec -T db psql -v ON_ERROR_STOP=1 -U odoo -d postgres -c 'CREATE DATABASE thutien_online OWNER thutien_app'
    Check-Exit 'Tạo database riêng cho bản cloud'
}

$venvPython = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    & python -m venv .venv
    Check-Exit 'Tạo Python virtual environment'
}
& $venvPython -m pip install -r backend/requirements.txt --disable-pip-version-check
Check-Exit 'Cài Python dependencies'

Push-Location (Join-Path $repo 'frontend')
try {
    & npm.cmd ci
    Check-Exit 'Cài frontend dependencies'
    & npm.cmd run build
    Check-Exit 'Build frontend'
} finally { Pop-Location }

# This probe intentionally prints only the count, never invoices or credentials.
$invoiceCount = & $venvPython -c 'from backend.app import db, odoo_reader; db.init_schema(); print(len(odoo_reader.open_invoices()))'
Check-Exit 'Kết nối Odoo Online'
Write-Host "Odoo Online: OK ($invoiceCount hóa đơn VND còn nợ). Dữ liệu ứng dụng ở thutien_online."
& $venvPython scripts/seed_users.py
Check-Exit 'Tạo tài khoản demo'

if ($WithOllama) {
    $modelRows = & docker @compose exec -T ollama ollama list
    Check-Exit 'Kiểm tra model Ollama'
    $modelPattern = '(?m)^' + [regex]::Escape($Model) + '\s'
    if (($modelRows -join "`n") -notmatch $modelPattern) {
        & docker @compose exec -T ollama ollama pull $Model
        Check-Exit 'Tải model Ollama'
    }
}

function Find-FreePort([int]$Preferred) {
    for ($candidate = $Preferred; $candidate -le [Math]::Min($Preferred + 19, 65535); $candidate++) {
        $listener = $null
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $candidate)
            $listener.Start()
            return $candidate
        } catch [System.Net.Sockets.SocketException] {
            continue
        } finally {
            if ($listener) { $listener.Stop() }
        }
    }
    throw "Không có cổng trống từ $Preferred đến $($Preferred + 19)."
}

$Port = Find-FreePort $Port
Write-Host "Mở http://127.0.0.1:$Port/app/ (nguồn Odoo Online). Ctrl+C để dừng backend."
& $venvPython -m uvicorn backend.app.main:app --host 127.0.0.1 --port $Port
Check-Exit 'Backend'
