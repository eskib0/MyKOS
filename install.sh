#!/usr/bin/env bash
# ==============================================================================
# Instalador oficial del ecosistema MyKOS para Linux
# ==============================================================================
set -euo pipefail

MYKOS_ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
LOCAL_BIN="$HOME/.local/bin"
VENV_DIR="${MYKOS_VENV_DIR:-$HOME/.mykos/venv}"
STATE_DIR="${MYKOS_GATEWAY_STATE_DIR:-$HOME/.mykos/gateway-state}"
WITH_VENV=1
WITH_SYSTEMD=0
WITH_DESKTOP=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-venv) WITH_VENV=0; shift ;;
    --systemd) WITH_SYSTEMD=1; shift ;;
    --no-desktop) WITH_DESKTOP=0; shift ;;
    --help|-h)
      cat <<EOF
Uso: ./install.sh [opciones]

Opciones:
  --no-venv      No crear ni actualizar el entorno virtual ~/.mykos/venv
  --systemd      Instalar y habilitar el servicio de usuario systemd (mykos-gateway.service)
  --no-desktop   No instalar los accesos directos (.desktop) en ~/.local/share/applications
EOF
      exit 0
      ;;
    *) shift ;;
  esac
done

echo "============================================================"
echo "  Instalador de MyKOS Ecosystem"
echo "  Raíz del proyecto: $MYKOS_ROOT"
echo "============================================================"

# 1. Comprobar requisitos básicos
if ! command -v node >/dev/null 2>&1; then
  echo "❌ Error: Node.js no está instalado. MyKOS requiere Node.js (>= 20)." >&2
  exit 1
fi
NODE_MAJOR=$(node -v 2>/dev/null | tr -d 'v' | cut -d. -f1)
if [ -z "$NODE_MAJOR" ] || [ "$NODE_MAJOR" -lt 20 ]; then
  echo "❌ Error: Se detectó Node.js $(node -v). MyKOS requiere Node.js >= 20.0.0." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ Error: Python 3 no está instalado. MyKOS requiere Python 3 (>= 3.10)." >&2
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "❌ Error: Se detectó $(python3 --version 2>&1). MyKOS requiere Python >= 3.10." >&2
  exit 1
fi

echo "✔ Node.js $(node -v) y $(python3 --version) detectados."
if [ "$NODE_MAJOR" -lt 22 ]; then
  echo "ℹ Nota: El motor de ingeniería inversa REA requiere Node.js >= 22.19.0 para herramientas avanzadas."
fi

# 2. Permisos de ejecución en lanzadores
chmod 755 "$MYKOS_ROOT/bin/mykos" \
          "$MYKOS_ROOT/gateway/runtime/mykos-gateway.mjs" \
          "$MYKOS_ROOT/apps/monitor/mykos-monitor" \
          "$MYKOS_ROOT/apps/monitor/mycos-monitor.py" \
          "$MYKOS_ROOT/apps/analizador/analizador-mykos"

# 3. Directorios de estado privado
mkdir -p "$STATE_DIR" "$HOME/.mykos/workspace" "$LOCAL_BIN"
chmod 700 "$HOME/.mykos" "$STATE_DIR" "$HOME/.mykos/workspace" 2>/dev/null || true

# 4. Entorno virtual Python (opcional, activado por defecto)
if [[ "$WITH_VENV" -eq 1 ]]; then
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "▶ Creando entorno virtual en $VENV_DIR..."
    python3 -m venv --system-site-packages "$VENV_DIR"
  fi
  echo "▶ Instalando dependencias ligeras del Gateway en $VENV_DIR..."
  "$VENV_DIR/bin/pip" install --quiet --upgrade pip
  "$VENV_DIR/bin/pip" install --quiet -r "$MYKOS_ROOT/gateway/app/requirements.txt"
  echo "✔ Entorno virtual listo en $VENV_DIR"
fi

# 5. Enlaces simbólicos en ~/.local/bin
ln -sf "$MYKOS_ROOT/bin/mykos" "$LOCAL_BIN/mykos"
ln -sf "$MYKOS_ROOT/apps/monitor/mykos-monitor" "$LOCAL_BIN/mykos-monitor"
ln -sf "$MYKOS_ROOT/apps/analizador/analizador-mykos" "$LOCAL_BIN/analizador-mykos"
echo "✔ Comandos enlazados en $LOCAL_BIN:"
echo "  • mykos"
echo "  • mykos-monitor"
echo "  • analizador-mykos"

# 6. Accesos directos de escritorio (.desktop)
if [[ "$WITH_DESKTOP" -eq 1 ]]; then
  APPS_DIR="$HOME/.local/share/applications"
  ICONS_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
  mkdir -p "$APPS_DIR" "$ICONS_DIR"
  cp -f "$MYKOS_ROOT/apps/monitor/mykos-monitor-icon.png" "$ICONS_DIR/mykos-monitor.png"
  cp -f "$MYKOS_ROOT/apps/monitor/mycos-monitor.desktop" "$APPS_DIR/mykos-monitor.desktop"
  echo "✔ Acceso directo de escritorio instalado en $APPS_DIR/mykos-monitor.desktop"
fi

# 7. Servicio systemd de usuario (opcional con --systemd)
if [[ "$WITH_SYSTEMD" -eq 1 ]]; then
  SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
  mkdir -p "$SYSTEMD_USER_DIR"
  cat > "$SYSTEMD_USER_DIR/mykos-gateway.service" <<EOF
[Unit]
Description=MyKOS Gateway & AI Control Plane
After=network.target

[Service]
Type=simple
WorkingDirectory=$MYKOS_ROOT/gateway
Environment="MYKOS_BACKEND_PYTHON=$VENV_DIR/bin/python"
ExecStart=$(command -v node) $MYKOS_ROOT/gateway/runtime/mykos-gateway.mjs gateway --port 3210
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload || true
  systemctl --user enable mykos-gateway.service || true
  echo "✔ Servicio systemd instalado: systemctl --user start mykos-gateway"
fi

echo ""
echo "✅ Instalación completada. Prueba ahora:"
echo "   mykos test      # Verificar rutas, políticas y seguridad"
echo "   mykos run       # Arrancar MyKOS en vivo en http://127.0.0.1:3210"
echo "   mykos status    # Consultar el estado de todos los servicios"
