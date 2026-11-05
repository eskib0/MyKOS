# ==============================================================================
# Helper para compilar el instalador de Windows (Inno Setup 6)
# ==============================================================================
param(
    [switch]$FullOffline = $false
)
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MykosRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$RuntimeDir = Join-Path $MykosRoot "runtime"
$DistDir = Join-Path $MykosRoot "dist"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Compilador de Instalador MyKOS para Windows" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Si se solicita modo Full Offline, descargar Python embebido y Node portable
if ($FullOffline) {
    New-Item -ItemType Directory -Force -Path (Join-Path $RuntimeDir "python"), (Join-Path $RuntimeDir "node") | Out-Null

    # 1. Node.js portable
    $nodeExe = Join-Path $RuntimeDir "node\node.exe"
    if (-not (Test-Path $nodeExe)) {
        Write-Host "▶ Descargando Node.js v20 portable..." -ForegroundColor Cyan
        $nodeZip = Join-Path $RuntimeDir "node.zip"
        Invoke-WebRequest -Uri "https://nodejs.org/dist/v20.18.0/win-x64/node.exe" -OutFile $nodeExe
    }

    # 2. Python 3.12 embeddable
    $pyExe = Join-Path $RuntimeDir "python\python.exe"
    if (-not (Test-Path $pyExe)) {
        Write-Host "▶ Descargando Python 3.12 embebido..." -ForegroundColor Cyan
        $pyZip = Join-Path $RuntimeDir "python-embed.zip"
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip" -OutFile $pyZip
        Expand-Archive -Path $pyZip -DestinationPath (Join-Path $RuntimeDir "python") -Force
        Remove-Item $pyZip -Force
    }
}

# 3. Localizar compilador Inno Setup (ISCC.exe)
$isccPaths = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $isccPaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    if (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue) {
        $iscc = "ISCC.exe"
    } else {
        Write-Error "❌ No se encontró Inno Setup 6 (ISCC.exe). Instálalo con: winget install JRSoftware.InnoSetup"
        exit 1
    }
}

Write-Host "▶ Compilando con Inno Setup: $iscc ..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
& $iscc (Join-Path $ScriptDir "mykos-setup.iss")

Write-Host "============================================================" -ForegroundColor Green
Write-Host "  ✅ Instalador compilado con éxito en dist\" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
