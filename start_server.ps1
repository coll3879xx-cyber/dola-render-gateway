$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$out = Join-Path $scriptDir 'server.log'
$err = Join-Path $scriptDir 'server.err.log'

Write-Host "Starting Dola Pool server..." -ForegroundColor Cyan

if (Test-Path $out) { Remove-Item $out -Force -ErrorAction SilentlyContinue }
if (Test-Path $err) { Remove-Item $err -Force -ErrorAction SilentlyContinue }

Start-Process -FilePath 'py.exe' -ArgumentList '-3','-m','uvicorn','server:app','--host','0.0.0.0','--port','8000' -WorkingDirectory $scriptDir -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Normal

Start-Sleep -Seconds 3
Write-Host "Server running at http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Admin dashboard available at http://127.0.0.1:8000/web" -ForegroundColor Yellow
