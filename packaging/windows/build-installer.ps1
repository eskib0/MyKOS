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

    function Assert-FileHash($filePath, $expectedHash) {
        $actualHash = (Get-FileHash -Path $filePath -Algorithm SHA256).Hash.ToLower()
        if ($actualHash -ne $expectedHash.ToLower()) {
            Remove-Item $filePath -Force -ErrorAction SilentlyContinue
            Write-Error "❌ Verificación de integridad SHA-256 fallida para $filePath. Esperado: $expectedHash, Obtenido: $actualHash"
            exit 1
        }
    }

    # 1. Node.js portable
    $nodeExe = Join-Path $RuntimeDir "node\node.exe"
    $nodeExpectedSha256 = "35b7c95a379beb606f5798ed83081690df13190077630b234163c6607aa4cc94"
    if (-not (Test-Path $nodeExe)) {
        Write-Host "▶ Descargando Node.js v20 portable..." -ForegroundColor Cyan
        Invoke-WebRequest -Uri "https://nodejs.org/dist/v20.18.0/win-x64/node.exe" -OutFile $nodeExe
        Assert-FileHash $nodeExe $nodeExpectedSha256
    }

    # 2. Python 3.12 embeddable
    $pyExe = Join-Path $RuntimeDir "python\python.exe"
    $pyExpectedSha256 = "0d57bb6cb078b74d23dbfe91f77d6780d45bed328911609f1f7ee2ba1606bf44"
    if (-not (Test-Path $pyExe)) {
        Write-Host "▶ Descargando Python 3.12 embebido..." -ForegroundColor Cyan
        $pyZip = Join-Path $RuntimeDir "python-embed.zip"
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip" -OutFile $pyZip
        Assert-FileHash $pyZip $pyExpectedSha256
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
