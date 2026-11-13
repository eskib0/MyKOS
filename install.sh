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

# 1. Comprobar e instalar requisitos básicos (Node.js >= 20 y Python >= 3.10)
if [[ -d "$HOME/.mykos/runtime/node/bin" ]]; then
  export PATH="$HOME/.mykos/runtime/node/bin:$PATH"
fi

NEED_NODE=0
if ! command -v node >/dev/null 2>&1; then
  NEED_NODE=1
else
  NODE_MAJOR=$(node -v 2>/dev/null | tr -d 'v' | cut -d. -f1 || echo 0)
  if [ -z "$NODE_MAJOR" ] || [ "$NODE_MAJOR" -lt 20 ]; then
    NEED_NODE=1
  fi
fi

if [[ "$NEED_NODE" -eq 1 ]]; then
  echo "▶ Descargando Node.js v20 LTS portátil en $HOME/.mykos/runtime/node..."
  mkdir -p "$HOME/.mykos/runtime/node"
  ARCH_UNAME="$(uname -m)"
  NODE_ARCH="x64"
  [[ "$ARCH_UNAME" == "aarch64" || "$ARCH_UNAME" == "arm64" ]] && NODE_ARCH="arm64"
  curl -fsSL "https://nodejs.org/dist/v20.18.0/node-v20.18.0-linux-${NODE_ARCH}.tar.xz" \
    | tar -xJ --strip-components=1 -C "$HOME/.mykos/runtime/node"
  export PATH="$HOME/.mykos/runtime/node/bin:$PATH"
  NODE_MAJOR=$(node -v 2>/dev/null | tr -d 'v' | cut -d. -f1 || echo 20)
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

# 5. Enlaces simbólicos en ~/.local/bin y prioridad en PATH
ln -sf "$MYKOS_ROOT/bin/mykos" "$LOCAL_BIN/mykos"
ln -sf "$MYKOS_ROOT/apps/monitor/mykos-monitor" "$LOCAL_BIN/mykos-monitor"
ln -sf "$MYKOS_ROOT/apps/analizador/analizador-mykos" "$LOCAL_BIN/analizador-mykos"
for rc_file in "$HOME/.bashrc" "$HOME/.profile"; do
  if [[ -f "$rc_file" ]] && ! grep -q 'export PATH="$HOME/.local/bin:$PATH"' "$rc_file" 2>/dev/null; then
    printf '\n# MyKOS CLI priority path\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rc_file"
  fi
done
export PATH="$LOCAL_BIN:$PATH"
echo "✔ Comandos enlazados en $LOCAL_BIN:"
echo "  • mykos"
echo "  • mykos-monitor"
echo "  • analizador-mykos"

# 5b. Sincronizar rutas en mykos-gateway.json hacia esta instalación ($MYKOS_ROOT)
CONFIG_FILE="$STATE_DIR/mykos-gateway.json"
python3 - "$CONFIG_FILE" "$HOME/.mykos/workspace" "$MYKOS_ROOT/gateway/app" "$VENV_DIR/bin/python" <<'PY'
import json, os, sys
cfg_path, ws_dir, app_dir, venv_py = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
plugin_dir = os.path.join(app_dir, "gateway-plugin", "mykos-ui")
py_bin = venv_py if os.path.exists(venv_py) else "python3"
cfg = {}
if os.path.exists(cfg_path):
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
cfg.setdefault("gateway", {"host": "127.0.0.1", "port": 3210})
cfg.setdefault("agents", {"defaults": {"workspace": ws_dir}})
cfg.setdefault("plugins", {})["load"] = {"paths": [plugin_dir]}
entry = cfg["plugins"].setdefault("entries", {}).setdefault("mykos-ui", {"enabled": True, "config": {}})
ecfg = entry.setdefault("config", {})
ecfg["projectDir"] = app_dir
ecfg["staticDir"] = os.path.join(app_dir, "static")
ecfg.setdefault("store", {"enabled": True})
ecfg.setdefault("chatLoop", {"enabled": True})
b = ecfg.setdefault("backend", {"url": "http://127.0.0.1:3211", "spawn": True})
b["python"] = py_bin
b["script"] = os.path.join(app_dir, "server.py")
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
os.chmod(cfg_path, 0o600)
PY
echo "✔ Configuración del Gateway sincronizada hacia $MYKOS_ROOT/gateway/app"

# 6. Accesos directos de escritorio (.desktop)
if [[ "$WITH_DESKTOP" -eq 1 ]]; then
  APPS_DIR="$HOME/.local/share/applications"
  ICONS_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
  ICONS_512_DIR="$HOME/.local/share/icons/hicolor/512x512/apps"
  mkdir -p "$APPS_DIR" "$ICONS_DIR" "$ICONS_512_DIR"
  cp -f "$MYKOS_ROOT/apps/monitor/mykos-monitor-icon.png" "$ICONS_DIR/mykos-monitor.png"
  cp -f "$MYKOS_ROOT/apps/monitor/mycos-monitor.desktop" "$APPS_DIR/mykos-monitor.desktop"
  if [[ -f "$MYKOS_ROOT/packaging/assets/mykos.png" ]]; then
    cp -f "$MYKOS_ROOT/packaging/assets/mykos.png" "$ICONS_512_DIR/mykos.png"
  fi
  cat > "$APPS_DIR/mykos.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=MyKOS
GenericName=Asistente de IA Local
Comment=Asistente de IA local soberano, multimodal y ligero con Gateway propio
Exec=$LOCAL_BIN/mykos open
Icon=mykos
Terminal=false
Categories=Utility;Development;ArtificialIntelligence;
Keywords=AI;LLM;Assistant;MyKOS;Ollama;Voice;
StartupNotify=true
EOF
  chmod 644 "$APPS_DIR/mykos.desktop"
  echo "✔ Accesos directos de escritorio instalados en $APPS_DIR (mykos.desktop y mykos-monitor.desktop)"
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

# 8. Si había un proceso previo corriendo en memoria, reiniciarlo con la nueva versión
if pgrep -f "mykos-gateway\.mjs" >/dev/null 2>&1; then
  echo "▶ Detectada instancia previa de MyKOS en ejecución; reiniciando con la versión nueva..."
  "$MYKOS_ROOT/bin/mykos" restart || true
fi

echo ""
echo "✅ Instalación completada. Prueba ahora:"
echo "   mykos test      # Verificar rutas, políticas y seguridad"
echo "   mykos run       # Arrancar MyKOS en vivo en http://127.0.0.1:3210"
echo "   mykos status    # Consultar el estado de todos los servicios"
