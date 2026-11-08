# ==============================================================================
# Instalador oficial del ecosistema MyKOS para Windows (PowerShell)
# ==============================================================================
param(
    [switch]$NoVenv,
    [switch]$NoDesktop
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$MykosRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BinDir = Join-Path $MykosRoot "bin"
$VenvDir = if ($env:MYKOS_VENV_DIR) { $env:MYKOS_VENV_DIR } else { Join-Path $HOME ".mykos\venv" }
$StateDir = if ($env:MYKOS_GATEWAY_STATE_DIR) { $env:MYKOS_GATEWAY_STATE_DIR } else { Join-Path $HOME ".mykos\gateway-state" }
$WorkspaceDir = Join-Path $HOME ".mykos\workspace"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Instalador de MyKOS Ecosystem (Windows)" -ForegroundColor Cyan
Write-Host "  Raíz del proyecto: $MykosRoot" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Comprobar Node.js y Python (o descargar runtimes portables automáticamente)
$RuntimeDir = Join-Path $MykosRoot "runtime"
$BundledNodeExe = Join-Path $RuntimeDir "node\node.exe"
if (Test-Path $BundledNodeExe) {
    $env:PATH = "$(Join-Path $RuntimeDir 'node');$env:PATH"
}
try {
    $nodeVer = & node -v
} catch {
    Write-Host "▶ Node.js no detectado; descargando Node.js v20 portátil en $RuntimeDir\node..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path (Join-Path $RuntimeDir "node") | Out-Null
    Invoke-WebRequest -Uri "https://nodejs.org/dist/v20.18.0/win-x64/node.exe" -OutFile $BundledNodeExe
    $env:PATH = "$(Join-Path $RuntimeDir 'node');$env:PATH"
    $nodeVer = & $BundledNodeExe -v
}

$HasSystemPy = $false
try {
    $pyCmd = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($pyCmd -and $pyCmd.Source -and ($pyCmd.Source -notmatch "WindowsApps")) {
        $pyVer = & python --version
        if ($LASTEXITCODE -eq 0) { $HasSystemPy = $true }
    }
} catch {}

if (-not $HasSystemPy) {
    $pyDir = Join-Path $RuntimeDir "python"
    $pyExe = Join-Path $pyDir "python.exe"
    if (-not (Test-Path $pyExe)) {
        Write-Host "▶ Python 3 no detectado; descargando Python 3.12 embebido en $pyDir..." -ForegroundColor Cyan
        New-Item -ItemType Directory -Force -Path $pyDir | Out-Null
        $pyZip = Join-Path $RuntimeDir "python-embed.zip"
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip" -OutFile $pyZip
        Expand-Archive -Path $pyZip -DestinationPath $pyDir -Force
        Remove-Item $pyZip -Force
    }
    $pthFile = Join-Path $pyDir "python312._pth"
    Set-Content -Path $pthFile -Value ("python312.zip`r`n.`r`nLib\site-packages`r`n..\..\gateway\app`r`nimport site") -Encoding ASCII
    $getPip = Join-Path $pyDir "get-pip.py"
    if (-not (Test-Path (Join-Path $pyDir "Scripts\pip.exe"))) {
        Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip
        & $pyExe $getPip --quiet
        Remove-Item $getPip -Force -ErrorAction SilentlyContinue
    }
    & $pyExe -m pip install --quiet -r (Join-Path $MykosRoot "gateway\app\requirements.txt")
    $pyVer = & $pyExe --version
    $NoVenv = $true
}
Write-Host "✔ Node.js $nodeVer y $pyVer listos." -ForegroundColor Green

# 2. Crear carpetas de estado
New-Item -ItemType Directory -Force -Path $StateDir, $WorkspaceDir | Out-Null

# 3. Crear entorno virtual Python e instalar requirements.txt
if (-not $NoVenv) {
    $venvPy = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        Write-Host "▶ Creando entorno virtual en $VenvDir..." -ForegroundColor Cyan
        & python -m venv $VenvDir
    }
    Write-Host "▶ Instalando dependencias del Gateway en $VenvDir..." -ForegroundColor Cyan
    & $venvPy -m pip install --quiet --upgrade pip
    & $venvPy -m pip install --quiet -r (Join-Path $MykosRoot "gateway\app\requirements.txt")
    Write-Host "✔ Entorno virtual listo en $VenvDir" -ForegroundColor Green
}

# 4. Añadir MyKOS\bin al PATH del usuario en Windows
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
$pathItems = $userPath -split ";" | Where-Object { $_ -ne "" }
if ($pathItems -notcontains $BinDir) {
    $newPath = ($pathItems + $BinDir) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    $env:Path = "$env:Path;$BinDir"
    Write-Host "✔ Añadido $BinDir al PATH de tu usuario en Windows." -ForegroundColor Green
} else {
    Write-Host "✔ $BinDir ya está en el PATH de tu usuario." -ForegroundColor Green
}

# 5. Crear acceso directo en el Escritorio (opcional)
if (-not $NoDesktop) {
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $wsh = New-Object -ComObject WScript.Shell
        $shortcut = $wsh.CreateShortcut((Join-Path $desktop "MyKOS Live Run.lnk"))
        $shortcut.TargetPath = "powershell.exe"
        $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$BinDir\mykos.ps1`" run"
        $shortcut.WorkingDirectory = $MykosRoot
        $shortcut.Description = "Iniciar MyKOS Gateway y ver logs en vivo"
        $shortcut.Save()
        Write-Host "✔ Acceso directo «MyKOS Live Run.lnk» creado en el Escritorio." -ForegroundColor Green
    } catch {
        Write-Host "⚠️  No se pudo crear el acceso directo en el Escritorio: $_" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "✅ Instalación en Windows completada. Abre una terminal nueva y ejecuta:" -ForegroundColor Green
Write-Host "   mykos test      # Verificar rutas, políticas y seguridad"
Write-Host "   mykos run       # Arrancar MyKOS en vivo en http://127.0.0.1:3210"
Write-Host "   mykos status    # Consultar el estado de todos los servicios"
