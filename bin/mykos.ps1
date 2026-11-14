# ==============================================================================
# MyKOS CLI (Windows PowerShell) — Herramienta unificada para el ecosistema MyKOS
# ==============================================================================
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$BinDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MykosRoot = Split-Path -Parent $BinDir
$GatewayDir = Join-Path $MykosRoot "gateway"
$RuntimeMjs = Join-Path $GatewayDir "runtime\mykos-gateway.mjs"
$StoreCli = Join-Path $GatewayDir "app\gateway-plugin\store-cli.mjs"

$StateDir = if ($env:MYKOS_GATEWAY_STATE_DIR) { $env:MYKOS_GATEWAY_STATE_DIR } else { Join-Path $HOME ".mykos\gateway-state" }
$WorkspaceDir = if ($env:MYKOS_GATEWAY_WORKSPACE_DIR) { $env:MYKOS_GATEWAY_WORKSPACE_DIR } else { Join-Path $HOME ".mykos\workspace" }
$PidFile = Join-Path $StateDir "mykos-gateway.pid"
$GatewayLog = Join-Path $StateDir "mykos-gateway.log"
$AppDataDir = Join-Path $GatewayDir "app\data"
$BackendLog = Join-Path $AppDataDir "mykos-backend.log"
try {
    New-Item -ItemType Directory -Force -Path $AppDataDir -ErrorAction Stop | Out-Null
    $probeFile = Join-Path $AppDataDir ".write-probe-$PID"
    Set-Content -Path $probeFile -Value "" -ErrorAction Stop
    Remove-Item $probeFile -Force -ErrorAction SilentlyContinue
} catch {
    $BackendLog = Join-Path $StateDir "mykos-backend.log"
}
$ConfigFile = if ($env:MYKOS_GATEWAY_CONFIG) { $env:MYKOS_GATEWAY_CONFIG } else { Join-Path $StateDir "mykos-gateway.json" }
$DefaultPort = if ($env:MYKOS_GATEWAY_PORT) { [int]$env:MYKOS_GATEWAY_PORT } else { 3210 }

# Si existe Node.js embebido en runtime\node o en ~/.mykos/runtime/node, añadirlo al inicio del PATH
foreach ($nodeDir in @((Join-Path $MykosRoot "runtime\node"), (Join-Path $HOME ".mykos\runtime\node"))) {
    if (Test-Path (Join-Path $nodeDir "node.exe")) {
        $env:PATH = "$nodeDir;$env:PATH"
    }
}

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

function Get-MykosNode {
    foreach ($candidate in @(
        (Join-Path $MykosRoot "runtime\node\node.exe"),
        (Join-Path $HOME ".mykos\runtime\node\node.exe")
    )) {
        if (Test-Path $candidate) { return $candidate }
    }
    $cmd = Get-Command "node.exe" -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    $userNodeDir = Join-Path $HOME ".mykos\runtime\node"
    $userNodeExe = Join-Path $userNodeDir "node.exe"
    Write-Host "▶ Descargando Node.js v20 portátil para MyKOS..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $userNodeDir | Out-Null
    Invoke-WebRequest -Uri "https://nodejs.org/dist/v20.18.0/win-x64/node.exe" -OutFile $userNodeExe
    $env:PATH = "$userNodeDir;$env:PATH"
    return $userNodeExe
}

function Show-MykosLogo {
    param([string]$Subtitle = "AI Gateway · Local & Cloud Intelligence · Voice Engine")
    Write-Host ""
    Write-Host "  ███╗   ███╗██╗   ██╗██╗  ██╗ ██████╗ ███████╗" -ForegroundColor Cyan
    Write-Host "  ████╗ ████║╚██╗ ██╔╝██║ ██╔╝██╔═══██╗██╔════╝" -ForegroundColor Cyan
    Write-Host "  ██╔████╔██║ ╚████╔╝ █████╔╝ ██║   ██║███████╗" -ForegroundColor Blue
    Write-Host "  ██║╚██╔╝██║  ╚██╔╝  ██╔═██╗ ██║   ██║╚════██║" -ForegroundColor Blue
    Write-Host "  ██║ ╚═╝ ██║   ██║   ██║  ██╗╚██████╔╝███████║" -ForegroundColor DarkCyan
    Write-Host "  ╚═╝     ╚═╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝" -ForegroundColor DarkCyan
    Write-Host "  $Subtitle" -ForegroundColor DarkGray
    Write-Host ""
}

function Get-MykosPython {
    if ($env:MYKOS_BACKEND_PYTHON -and (Test-Path $env:MYKOS_BACKEND_PYTHON)) { return $env:MYKOS_BACKEND_PYTHON }
    foreach ($candidate in @(
        (Join-Path $MykosRoot "runtime\python\python.exe"),
        (Join-Path $MykosRoot "runtime\python\Scripts\python.exe"),
        (Join-Path $HOME ".mykos\venv\Scripts\python.exe"),
        (Join-Path $HOME ".mykos\runtime\python\python.exe")
    )) {
        if (Test-Path $candidate) { return $candidate }
    }
    $cmd = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and ($cmd.Source -notmatch "WindowsApps")) { return $cmd.Source }
    return "python"
}

function Resolve-MykosPort {
    if ($env:MYKOS_GATEWAY_PORT) { return [int]$env:MYKOS_GATEWAY_PORT }
    if (Test-Path $ConfigFile) {
        try {
            $cfg = Get-Content $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($cfg.gateway.port) { return [int]$cfg.gateway.port }
        } catch {}
    }
    return $DefaultPort
}

function Get-MykosProcess {
    if (Test-Path $PidFile) {
        try {
            $savedPid = [int](Get-Content $PidFile -ErrorAction Stop).Trim()
            $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
            if ($proc) { return $proc }
        } catch {}
    }
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "mykos-gateway\.mjs" }
    if ($procs) {
        $first = $procs | Select-Object -First 1
        return Get-Process -Id $first.ProcessId -ErrorAction SilentlyContinue
    }
    return $null
}

function Invoke-MykosStop {
    $proc = Get-MykosProcess
    $nodeProcs = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "mykos-gateway\.mjs" }
    $pyProcs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "gateway[\\/]app[\\/]server\.py" }

    if (-not $proc -and -not $nodeProcs -and -not $pyProcs) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        Write-Host "MyKOS Gateway ya está detenido."
        return
    }
    Write-Host "Deteniendo MyKOS Gateway..."
    if ($proc) {
        try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
        try { Start-Process -FilePath "taskkill" -ArgumentList @("/pid", "$($proc.Id)", "/T", "/F") -WindowStyle Hidden -Wait -ErrorAction SilentlyContinue } catch {}
    }
    foreach ($np in $nodeProcs) {
        try { Stop-Process -Id $np.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
        try { Start-Process -FilePath "taskkill" -ArgumentList @("/pid", "$($np.ProcessId)", "/T", "/F") -WindowStyle Hidden -Wait -ErrorAction SilentlyContinue } catch {}
    }
    foreach ($pp in $pyProcs) {
        try { Stop-Process -Id $pp.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
        try { Start-Process -FilePath "taskkill" -ArgumentList @("/pid", "$($pp.ProcessId)", "/T", "/F") -WindowStyle Hidden -Wait -ErrorAction SilentlyContinue } catch {}
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    Write-Host "✅ MyKOS Gateway detenido." -ForegroundColor Green
}

function Invoke-MykosStart {
    param([int]$Port = (Resolve-MykosPort), [switch]$Foreground)
    $existing = Get-MykosProcess
    if ($existing) {
        Write-Host "MyKOS Gateway ya está en marcha (PID $($existing.Id)) en http://127.0.0.1:$Port" -ForegroundColor Green
        return
    }
    $nodeExe = Get-MykosNode
    $pyExe = Get-MykosPython
    $env:MYKOS_BACKEND_PYTHON = $pyExe
    $env:MYKOS_GATEWAY_STATE_DIR = $StateDir
    if ($Foreground) {
        Show-MykosLogo "MyKOS Gateway · Modo Primer Plano (http://127.0.0.1:$Port)"
        & $nodeExe $RuntimeMjs gateway --port $Port
        return
    }
    Write-Host "Arrancando MyKOS Gateway en segundo plano (puerto $Port)..."
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $GatewayLog) | Out-Null
    $procId = $null
    try {
        $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly
        $startup.ShowWindow = [uint16]0
        $nodeCmd = "cmd.exe /c `"set `"MYKOS_BACKEND_PYTHON=$pyExe`" && set `"MYKOS_GATEWAY_STATE_DIR=$StateDir`" && `"$nodeExe`" `"$RuntimeMjs`" gateway --port $Port > `"$GatewayLog`" 2> `"$GatewayLog.err`"`""
        $res = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
            CommandLine = $nodeCmd
            CurrentDirectory = $GatewayDir
            ProcessStartupInformation = $startup
        }
        if ($res -and $res.ReturnValue -eq 0 -and $res.ProcessId) {
            $procId = $res.ProcessId
        }
    } catch {}

    if (-not $procId) {
        $proc = Start-Process -FilePath $nodeExe -ArgumentList @($RuntimeMjs, "gateway", "--port", "$Port") `
            -WorkingDirectory $GatewayDir `
            -RedirectStandardOutput $GatewayLog -RedirectStandardError "$GatewayLog.err" `
            -WindowStyle Hidden -PassThru
        $procId = $proc.Id
    }
    Set-Content -Path $PidFile -Value $procId -Encoding ASCII

    for ($i = 0; $i -lt 30; $i++) {
        try {
            $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/mykos-health" -TimeoutSec 1 -ErrorAction Stop
            if ($resp.ok) {
                Write-Host "✅ MyKOS Gateway listo (PID $procId) -> http://127.0.0.1:$Port" -ForegroundColor Green
                return
            }
        } catch {}
        Start-Sleep -Milliseconds 300
    }
    Write-Host "⚠️  MyKOS Gateway arrancó (PID $procId) -> http://127.0.0.1:$Port" -ForegroundColor Yellow
}

function Invoke-MykosRun {
    param([int]$Port = (Resolve-MykosPort))
    Show-MykosLogo "MyKOS Live Run · http://127.0.0.1:$Port · Cerrar terminal o Ctrl+C detiene todo"

    if (Get-MykosProcess) {
        Write-Host "↻ Reiniciando instancia previa para tomar el control en esta ventana..." -ForegroundColor Yellow
        Invoke-MykosStop | Out-Null
    }

    $nodeExe = Get-MykosNode
    $env:MYKOS_BACKEND_PYTHON = Get-MykosPython
    $env:MYKOS_GATEWAY_STATE_DIR = $StateDir
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $GatewayLog) | Out-Null
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $BackendLog) | Out-Null
    if (-not (Test-Path $GatewayLog)) { New-Item -ItemType File -Force -Path $GatewayLog | Out-Null }
    if (-not (Test-Path $BackendLog)) { New-Item -ItemType File -Force -Path $BackendLog | Out-Null }

    $proc = Start-Process -FilePath $nodeExe -ArgumentList @($RuntimeMjs, "gateway", "--port", "$Port") `
        -WorkingDirectory $GatewayDir `
        -RedirectStandardOutput $GatewayLog -RedirectStandardError "$GatewayLog.err" `
        -NoNewWindow -PassThru
    Set-Content -Path $PidFile -Value $proc.Id -Encoding ASCII

    Write-Host "▶ MyKOS Gateway activo (PID $($proc.Id))" -ForegroundColor Green
    Write-Host "🌐 Interfaz Web: http://127.0.0.1:$Port/" -ForegroundColor Cyan
    Write-Host "   Para detenerlo: pulsa Ctrl+C o cierra esta ventana de terminal" -ForegroundColor DarkGray
    Write-Host ""

    try {
        Get-Content -Path $GatewayLog, $BackendLog -Tail 5 -Wait
    } finally {
        Write-Host ""
        Write-Host "⏹ Cerrando MyKOS Gateway y deteniendo todos los servicios asociados..." -ForegroundColor Yellow
        Invoke-MykosStop | Out-Null
    }
}

function Invoke-MykosStatus {
    $port = Resolve-MykosPort
    $proc = Get-MykosProcess
    if (-not $proc) {
        Write-Host "🔴 MyKOS Gateway: DETENIDO (puerto configurado: $port)" -ForegroundColor Red
        exit 1
    }
    Write-Host "🟢 MyKOS Gateway: ACTIVO (PID $($proc.Id)) · http://127.0.0.1:$port" -ForegroundColor Green
    try {
        $d = Invoke-RestMethod -Uri "http://127.0.0.1:$port/mykos-health" -TimeoutSec 2 -ErrorAction Stop
        $bState = if ($d.backend.up) { "ACTIVO" } else { $d.backend.phase }
        $sState = if ($d.store.active) { "ACTIVO" } else { "INACTIVO" }
        $loopOwner = if ($d.chatLoop.enabled) { "Gateway (nativo)" } else { "Worker" }
        Write-Host "   • Versión Gateway : $($d.version)"
        Write-Host "   • Backend Python  : $bState (PID $($d.backend.backendPid), $($d.backend.url))"
        Write-Host "   • Almacén ACID    : $sState ($($d.store.dir))"
        Write-Host "   • Rutas / Política: $($d.routes.known) rutas / $($d.policy.governed) políticas firmadas"
        Write-Host "   • Bucle de Chat   : $loopOwner"
    } catch {
        Write-Host "   ⚠️  No se pudo leer /mykos-health en http://127.0.0.1:$port/mykos-health" -ForegroundColor Yellow
    }
}

function Invoke-MykosLogs {
    param([switch]$Follow, [int]$Lines = 25)
    if ($Follow) {
        Show-MykosLogo "MyKOS Live Telemetry & Logs · Pulsa Ctrl+C para salir"
        if (-not (Test-Path $GatewayLog)) { New-Item -ItemType File -Force -Path $GatewayLog | Out-Null }
        if (-not (Test-Path $BackendLog)) { New-Item -ItemType File -Force -Path $BackendLog | Out-Null }
        Get-Content -Path $GatewayLog, $BackendLog -Tail $Lines -Wait
    } else {
        Show-MykosLogo "MyKOS Logs · Últimos registros del Gateway y Backend"
        Write-Host "━━━ Gateway Log ($GatewayLog) ━━━" -ForegroundColor Cyan
        if (Test-Path $GatewayLog) { Get-Content $GatewayLog -Tail $Lines } else { Write-Host "(sin registros aún)" }
        Write-Host ""
        Write-Host "━━━ Backend Log ($BackendLog) ━━━" -ForegroundColor Blue
        if (Test-Path $BackendLog) { Get-Content $BackendLog -Tail $Lines } else { Write-Host "(sin registros aún)" }
    }
}

function Invoke-MykosDoctor {
    param([switch]$Fix)
    Show-MykosLogo (if ($Fix) { "MyKOS Doctor · Diagnóstico y Reparación Automática (--fix)" } else { "MyKOS Doctor · Diagnóstico Integral del Sistema" })
    Write-Host "1. Entorno de Ejecución (Windows)" -ForegroundColor White
    try {
        $nv = & node -v
        Write-Host "  ✔ Node.js detectado ($nv)" -ForegroundColor Green
    } catch {
        Write-Host "  ✖ Node.js no encontrado" -ForegroundColor Red
    }
    $pyExe = Get-MykosPython
    try {
        $pv = & $pyExe --version
        Write-Host "  ✔ Python detectado ($pv -> $pyExe)" -ForegroundColor Green
    } catch {
        Write-Host "  ✖ Python 3 no encontrado" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "2. Almacén Transaccional ACID ($StateDir\mykos)" -ForegroundColor White
    if ($Fix) {
        & node $StoreCli repair
    } else {
        & node $StoreCli verify
    }
}

function Invoke-MykosUpdate {
    Show-MykosLogo "MyKOS Updater · Actualización del Sistema (Windows)"
    Write-Host "▶ Comprobando actualizaciones para MyKOS..." -ForegroundColor Cyan
    if (Test-Path (Join-Path $MykosRoot ".git")) {
        $curCommit = (& git -C $MykosRoot rev-parse --short HEAD).Trim()
        Write-Host "  Versión local instalada (commit): $curCommit" -ForegroundColor Gray
        Write-Host "▶ Consultando repositorio remoto en GitHub..." -ForegroundColor Cyan
        & git -C $MykosRoot fetch origin main --quiet
        $remoteCommit = (& git -C $MykosRoot rev-parse --short origin/main).Trim()
        if ($curCommit -eq $remoteCommit) {
            Write-Host "✅ Ya tienes la versión más reciente instalada ($curCommit). Todo al día." -ForegroundColor Green
            return
        }
        Write-Host "🚀 ¡Nueva versión disponible: $remoteCommit!" -ForegroundColor Yellow
        $dirty = (& git -C $MykosRoot status --porcelain).Trim()
        if ($dirty) {
            Write-Host "❌ Abortando actualización: se han detectado cambios locales sin confirmar en $MykosRoot." -ForegroundColor Red
            Write-Host "   Para evitar pérdida de datos, guarda o descarta tus cambios locales antes de actualizar." -ForegroundColor Yellow
            return
        }
        Write-Host "▶ Aplicando actualización de forma segura (fast-forward)..." -ForegroundColor Cyan
        & git -C $MykosRoot pull --ff-only origin main
        if ($LASTEXITCODE -ne 0) {
            Write-Host "❌ No se pudo aplicar la actualización con fast-forward (posible divergencia con origin/main)." -ForegroundColor Red
            return
        }
        $venvPy = Get-MykosPython
        if (Test-Path (Join-Path $GatewayDir "app\requirements.txt")) {
            Write-Host "▶ Verificando dependencias en Python..." -ForegroundColor Cyan
            & $venvPy -m pip install --quiet -r (Join-Path $GatewayDir "app\requirements.txt")
        }
        Write-Host "✅ Código actualizado con éxito a la versión $remoteCommit." -ForegroundColor Green
        $proc = Get-MykosProcess
        if ($proc) {
            Write-Host "↻ Reiniciando MyKOS Gateway para aplicar los cambios..." -ForegroundColor Yellow
            Invoke-MykosStop
            Invoke-MykosStart
        }
    } else {
        Write-Host "ℹ️  Esta instalación no utiliza Git directo. Descarga la nueva versión desde https://github.com/eskib0/MyKOS/releases" -ForegroundColor Yellow
    }
}

function Invoke-MykosTest {
    Write-Host "▶ Ejecutando pruebas del Gateway de MyKOS..." -ForegroundColor Cyan
    Push-Location (Join-Path $GatewayDir "app\gateway-plugin\tests")
    try {
        foreach ($t in @("probe-routes.cjs", "probe-policy.cjs", "probe-store.cjs", "probe-realtime-controller.cjs", "probe-gemini-live-tools.cjs")) {
            Write-Host "── $t ──"
            & node $t | Select-Object -Last 3
            if ($LASTEXITCODE -ne 0) { throw "Falló $t (código $LASTEXITCODE)." }
        }
        Write-Host "── test_antigravity_safety.py ──"
        $pyExe = Get-MykosPython
        & $pyExe test_antigravity_safety.py
        if ($LASTEXITCODE -ne 0) { throw "Falló test_antigravity_safety.py (código $LASTEXITCODE)." }
        Write-Host "── test_security_audit.py ──"
        & $pyExe (Join-Path $MykosRoot "tests\test_security_audit.py")
        if ($LASTEXITCODE -ne 0) { throw "Falló test_security_audit.py (código $LASTEXITCODE)." }
    } finally {
        Pop-Location
    }
    Write-Host "✅ Todas las pruebas superadas." -ForegroundColor Green
}

$Command = if ($args.Count -gt 0) { $args[0] } else { "status" }
$RestArgs = if ($args.Count -gt 1) { $args[1..($args.Count - 1)] } else { @() }

if ($Command -eq "gateway") {
    $Command = if ($RestArgs.Count -gt 0) { $RestArgs[0] } else { "status" }
    $RestArgs = if ($RestArgs.Count -gt 1) { $RestArgs[1..($RestArgs.Count - 1)] } else { @() }
}

switch ($Command) {
    { $_ -in @("run", "live") } { Invoke-MykosRun }
    { $_ -in @("start", "up", "on") } { Invoke-MykosStart -Foreground:($RestArgs -contains "--fg") }
    { $_ -in @("stop", "down", "off") } { Invoke-MykosStop }
    "restart" { Invoke-MykosStop; Invoke-MykosStart }
    { $_ -in @("status", "health") } { Invoke-MykosStatus }
    { $_ -in @("doctor", "diag") } { Invoke-MykosDoctor -Fix:($RestArgs -contains "--fix") }
    { $_ -in @("open", "ui") } {
        if (-not (Get-MykosProcess)) {
            Invoke-MykosStart
        }
        $p = Resolve-MykosPort
        Start-Process "http://127.0.0.1:$p"
    }
    { $_ -in @("logs", "log") } { Invoke-MykosLogs -Follow:($RestArgs -contains "-f" -or $RestArgs -contains "--follow") }
    "store" { & node $StoreCli @RestArgs }
    "swarm" {
        if (-not ($RestArgs -contains "--json" -or $RestArgs -contains "--help" -or $RestArgs -contains "-h")) {
            Show-MykosLogo "MyKOS Swarm · Motor Multi-Agente Nativo"
        }
        $pyExe = Get-MykosPython
        $env:PYTHONPATH = Join-Path $GatewayDir "app"
        $env:MYKOS_GATEWAY_STATE_DIR = $StateDir
        $env:MYKOS_GATEWAY_CONFIG = $ConfigFile
        $swarmArgs = if ($RestArgs.Count -gt 0) { $RestArgs } else { @("status") }
        & $pyExe -m swarm_cli @swarmArgs
    }
    "rea" {
        Show-MykosLogo "MyKOS · REA (Reverse Engineer Anything) Engine"
        $pyExe = Get-MykosPython
        $env:PYTHONPATH = Join-Path $GatewayDir "app"
        $sub = if ($RestArgs.Count -gt 0) { $RestArgs[0] } else { "status" }
        $q = if ($RestArgs.Count -gt 1) { $RestArgs[1] } else { "" }
        & $pyExe -c "import json, sys; from rea import rea_status, rea_list_tools, rea_inspect_binary; s=sys.argv[1]; q=sys.argv[2]; print(json.dumps(rea_status() if s=='status' else (rea_inspect_binary(q) if s=='inspect' else rea_list_tools(q)), indent=2, ensure_ascii=False))" $sub $q
    }
    "analizador" {
        $pyExe = Get-MykosPython
        & $pyExe (Join-Path $MykosRoot "apps\analizador\main.py") @RestArgs
    }
    { $_ -in @("test", "tests", "check") } { Invoke-MykosTest }
    { $_ -in @("update", "upgrade") } { Invoke-MykosUpdate }
    default {
        Show-MykosLogo "MyKOS CLI (Windows) · Gestión integral del ecosistema MyKOS"
        Write-Host "Uso: mykos <run|start|stop|restart|status|doctor [--fix]|open|logs [-f]|store|swarm|rea|analizador|test>"
    }
}
