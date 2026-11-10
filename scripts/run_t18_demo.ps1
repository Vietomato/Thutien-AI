# From the repository root: .\scripts\run_t18_demo.ps1
# Requires Docker Desktop, Python and Node.js. Ollama itself runs in Docker.
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$Port = 8001,
    [string]$Model = 'qwen3:4b'
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repo

function Require-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Thiếu $Name. $Hint"
    }
}

function Check-Exit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step thất bại (mã $LASTEXITCODE)." }
}

Require-Command 'docker' 'Hãy cài và mở Docker Desktop.'
Require-Command 'python' 'Hãy cài Python 3.12 trở lên.'
Require-Command 'npm.cmd' 'Hãy cài Node.js.'

$compose = @('compose', '-f', 'docker-compose.yml', '-f', 'docker-compose.ollama.yml')
Write-Host 'Đang khởi động PostgreSQL, Odoo và Ollama trong Docker...'
& docker @compose up -d
Check-Exit 'docker compose up'

# The base compose file may map PostgreSQL to 5433 or 5434 on different machines.
$portLine = & docker @compose port db 5432
Check-Exit 'Đọc cổng PostgreSQL'
$portMatch = [regex]::Match(($portLine -join ' '), ':(\d+)\s*$')
if (-not $portMatch.Success) { throw "Không đọc được cổng PostgreSQL: $portLine" }
$dbPort = $portMatch.Groups[1].Value

$pgReady = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    & docker @compose exec -T db pg_isready -U odoo -d postgres 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $pgReady = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $pgReady) { throw 'PostgreSQL trong Docker chưa sẵn sàng.' }

function Pg-Value([string]$Database, [string]$Sql) {
    $result = & docker @compose exec -T db psql -U odoo -d $Database -Atqc $Sql
    Check-Exit 'Kiểm tra PostgreSQL'
    return ($result -join '').Trim()
}

if ((Pg-Value 'postgres' "SELECT 1 FROM pg_database WHERE datname='odoo'") -ne '1') {
    throw 'Chưa có database odoo. Mở http://localhost:8069, tạo database odoo và cài ứng dụng Xuất hóa đơn trước.'
}
if (-not (Pg-Value 'odoo' "SELECT to_regclass('public.account_move')")) {
    throw 'Odoo chưa có bảng hóa đơn. Hãy cài ứng dụng Xuất hóa đơn trên http://localhost:8069 trước.'
}

$appRole = Pg-Value 'postgres' "SELECT 1 FROM pg_roles WHERE rolname='thutien_app'"
$appDb = Pg-Value 'postgres' "SELECT 1 FROM pg_database WHERE datname='thutien_app'"
$testDb = Pg-Value 'postgres' "SELECT 1 FROM pg_database WHERE datname='thutien_test'"
if (-not $appRole -and -not $appDb -and -not $testDb) {
    Write-Host 'Đang tạo application database và tài khoản chỉ dành cho ứng dụng...'
    Get-Content 'scripts/init_app_db.sql' -Raw -Encoding UTF8 | & docker @compose exec -T db psql -v ON_ERROR_STOP=1 -U odoo -d postgres
    Check-Exit 'Khởi tạo application database'
} elseif (-not $appRole -or -not $appDb -or -not $testDb) {
    throw 'Application database mới được tạo một phần. Xem bước thiết lập DB trong README để hoàn tất.'
}
if (-not (Pg-Value 'postgres' "SELECT 1 FROM pg_roles WHERE rolname='thutien_ro'")) {
    Write-Host 'Đang tạo tài khoản đọc Odoo...'
    Get-Content 'scripts/create_readonly_role.sql' -Raw -Encoding UTF8 | & docker @compose exec -T db psql -v ON_ERROR_STOP=1 -U odoo -d odoo
    Check-Exit 'Khởi tạo tài khoản đọc Odoo'
}

# First-run development defaults match scripts/init_app_db.sql and
# scripts/create_readonly_role.sql. Keep this file local; .gitignore excludes it.
$localEnv = Join-Path $repo '.env'
if (-not (Test-Path $localEnv)) {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $secret = [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
    $content = "APP_DB_PASSWORD=change-me`nODOO_RO_PASSWORD=change-me`nDEMO_PASSWORD=demo12345`nJWT_SECRET=$secret`nAS_OF_DATE=2026-11-09`n"
    [System.IO.File]::WriteAllText($localEnv, $content, [System.Text.UTF8Encoding]::new($false))
    Write-Host 'Đã tạo .env local. Nếu bạn đổi mật khẩu role PostgreSQL, hãy sửa .env cho khớp.'
}

$allowed = @('APP_DB_PASSWORD', 'ODOO_RO_PASSWORD', 'DEMO_PASSWORD', 'JWT_SECRET', 'AS_OF_DATE',
             'APP_DB_NAME', 'APP_DB_USER', 'ODOO_DB_NAME', 'ODOO_RO_USER')
foreach ($line in [System.IO.File]::ReadAllLines($localEnv)) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $key = $Matches[1]
        $value = $Matches[2].Trim().Trim('"').Trim("'")
        if ($key -in $allowed) {
            [Environment]::SetEnvironmentVariable($key, $value, 'Process')
        }
    }
}
$env:APP_DB_HOST = '127.0.0.1'
$env:ODOO_DB_HOST = '127.0.0.1'
$env:APP_DB_PORT = $dbPort
$env:ODOO_DB_PORT = $dbPort
$env:OLLAMA_URL = 'http://127.0.0.1:11435'
$env:OLLAMA_ENABLED = '1'
$env:OLLAMA_MODEL = $Model
$env:OLLAMA_TIMEOUT_SECONDS = '60'

$venvPython = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host 'Đang tạo Python virtual environment...'
    & python -m venv .venv
    Check-Exit 'Tạo Python virtual environment'
}
Write-Host 'Đang cài/kiểm tra Python dependencies...'
& $venvPython -m pip install -r backend/requirements.txt --disable-pip-version-check
Check-Exit 'Cài Python dependencies'

Write-Host 'Đang cài/kiểm tra frontend dependencies và build...'
Push-Location (Join-Path $repo 'frontend')
try {
    & npm.cmd ci
    Check-Exit 'npm ci'
    & npm.cmd run build
    Check-Exit 'Build frontend'
} finally { Pop-Location }

# Confirm the existing Odoo and application databases before downloading a model.
$invoiceCount = & $venvPython -c 'from backend.app import db, odoo_reader; db.init_schema(); print(len(odoo_reader.open_invoices()))'
if ($LASTEXITCODE -ne 0) {
    throw 'Database chưa sẵn sàng. Tạo DB odoo, cài Xuất hóa đơn và chạy phần thiết lập DB trong README; nếu đã làm rồi, kiểm tra mật khẩu trong .env.'
}
Write-Host "Odoo và application database: OK ($invoiceCount hóa đơn còn nợ)"
if ($invoiceCount -eq '0') {
    Write-Host 'Odoo chưa có hóa đơn còn nợ. Chạy scripts/seed_odoo.py với tài khoản Odoo để có dữ liệu demo.'
}
& $venvPython scripts/seed_users.py
Check-Exit 'Tạo tài khoản demo'

# Wait for Ollama to accept commands before checking the model cache.
$modelRows = @()
$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    $modelRows = & docker @compose exec -T ollama ollama list 2>$null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw 'Ollama trong Docker chưa sẵn sàng. Kiểm tra Docker Desktop.' }
$modelPattern = '(?m)^' + [regex]::Escape($Model) + '\s'
if (($modelRows -join "`n") -notmatch $modelPattern) {
    Write-Host "Đang tải model $Model lần đầu (model này được giữ trong Docker volume)..."
    & docker @compose exec -T ollama ollama pull $Model
    Check-Exit 'Tải model Ollama'
} else {
    Write-Host "Model $Model đã có trên máy."
}

Write-Host "Mở http://127.0.0.1:$Port/app/ trong trình duyệt. Ctrl+C để dừng backend."
& $venvPython -m uvicorn backend.app.main:app --host 127.0.0.1 --port $Port
Check-Exit 'Backend'
