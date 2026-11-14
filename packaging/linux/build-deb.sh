#!/usr/bin/env bash
# ==============================================================================
# Constructor de paquete Debian (.deb) para MyKOS Ecosystem
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MYKOS_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$MYKOS_ROOT/dist"

# 1. Obtener versión desde version.json
VERSION="$(python3 -c 'import json; print(json.load(open("'"$MYKOS_ROOT"'/version.json"))["version"])' 2>/dev/null || echo "1.0.0")"
ARCH="amd64"
PKG_NAME="mykos_${VERSION}_${ARCH}"
STAGE_DIR="$DIST_DIR/staging/$PKG_NAME"

echo "============================================================"
echo "  Construyendo paquete Debian: $PKG_NAME.deb"
echo "  Versión: $VERSION | Arquitectura: $ARCH"
echo "============================================================"

# 2. Limpiar y crear estructura del paquete
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/DEBIAN"
mkdir -p "$STAGE_DIR/opt/mykos"
mkdir -p "$STAGE_DIR/usr/bin"
mkdir -p "$STAGE_DIR/usr/share/applications"
mkdir -p "$STAGE_DIR/usr/share/icons/hicolor/512x512/apps"

# 3. Generar archivo DEBIAN/control
cat > "$STAGE_DIR/DEBIAN/control" <<EOF
Package: mykos
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Maintainer: Ruben <eskib0@github.com>
Depends: python3 (>= 3.10), python3-pip, python3-venv, curl, bash, ca-certificates, xz-utils
Recommends: nodejs
Homepage: https://github.com/eskib0/MyKOS
Description: MyKOS Ecosystem - Multi-Model Local AI Assistant & Gateway
 MyKOS es un asistente de IA local soberano, ligero y multimodal.
 Incluye Gateway en Node.js, backend supervisado en Python, bucle de
 herramientas, motor de voz y compatibilidad con Ollama, Strata y llama.cpp.
EOF

# 4. Generar scripts del mantenedor (postinst, prerm, postrm)
cat > "$STAGE_DIR/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
chmod +x /opt/mykos/bin/mykos /opt/mykos/gateway/runtime/mykos-gateway.mjs
ln -sf /opt/mykos/bin/mykos /usr/bin/mykos

mkdir -p /opt/mykos/gateway/app/data/uploads /opt/mykos/gateway/app/data/media
chmod -R go-rwx /opt/mykos/gateway/app/data

# Asegurar Node.js >= 20 en /opt/mykos/runtime/node si el sistema no lo tiene o es antiguo
NEED_NODE=1
if command -v node >/dev/null 2>&1; then
  NODE_MAJOR="$(node -v 2>/dev/null | tr -d 'v' | cut -d. -f1 || echo 0)"
  if [ "$NODE_MAJOR" -ge 20 ] 2>/dev/null; then
    NEED_NODE=0
  fi
fi
if [ "$NEED_NODE" -eq 1 ] && [ ! -x /opt/mykos/runtime/node/bin/node ]; then
  echo "▶ Descargando Node.js v20 LTS para MyKOS en /opt/mykos/runtime/node..."
  mkdir -p /opt/mykos/runtime/node
  ARCH_UNAME="$(uname -m)"
  NODE_ARCH="x64"
  [ "$ARCH_UNAME" = "aarch64" ] || [ "$ARCH_UNAME" = "arm64" ] && NODE_ARCH="arm64"
  curl -fsSL "https://nodejs.org/dist/v20.18.0/node-v20.18.0-linux-${NODE_ARCH}.tar.xz" \
    | tar -xJ --strip-components=1 -C /opt/mykos/runtime/node || true
fi

# Preparar entorno virtual Python compartido en /opt/mykos/runtime/venv
if command -v python3 >/dev/null 2>&1 && [ ! -x /opt/mykos/runtime/venv/bin/python ]; then
  echo "▶ Configurando entorno Python de MyKOS en /opt/mykos/runtime/venv..."
  mkdir -p /opt/mykos/runtime
  if python3 -m venv /opt/mykos/runtime/venv >/dev/null 2>&1; then
    /opt/mykos/runtime/venv/bin/pip install --quiet --upgrade pip >/dev/null 2>&1 || true
    /opt/mykos/runtime/venv/bin/pip install --quiet -r /opt/mykos/gateway/app/requirements.txt >/dev/null 2>&1 || true
  fi
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi

# Detener cualquier instancia previa en memoria para que el próximo arranque cargue la versión nueva
pkill -f "mykos-gateway\.mjs" >/dev/null 2>&1 || true

echo "============================================================"
echo "  ¡MyKOS instalado con éxito!"
echo "  Ejecuta 'mykos open' o búscalo en tu menú de aplicaciones."
echo "============================================================"
exit 0
EOF
chmod 755 "$STAGE_DIR/DEBIAN/postinst"

cat > "$STAGE_DIR/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ -x /usr/bin/mykos ]; then
  /usr/bin/mykos stop >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 755 "$STAGE_DIR/DEBIAN/prerm"

cat > "$STAGE_DIR/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
  rm -f /usr/bin/mykos
  rm -rf /opt/mykos/runtime
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
  fi
fi
exit 0
EOF
chmod 755 "$STAGE_DIR/DEBIAN/postrm"

# 5. Copiar ficheros del proyecto a /opt/mykos (excluyendo datos de usuario, secretos y cachés)
echo "▶ Copiando archivos del núcleo a /opt/mykos..."
rsync -a --exclude='.git' \
         --exclude='.gitignore' \
         --exclude='dist' \
         --exclude='packaging/staging' \
         --exclude='__pycache__' \
         --exclude='*.pyc' \
         --exclude='node_modules' \
         --exclude='gateway-state' \
         --exclude='*.log' \
         --exclude='skills' \
         --exclude='promo*' \
         --exclude='sliding_window_median.cpp' \
         --exclude='swm' \
         --exclude='*backup*' \
         --exclude='data/oauth' \
         --exclude='data/conversations.json' \
         --exclude='data/*.db*' \
         --exclude='data/media' \
         --exclude='gateway/app/data/*.json' \
         --exclude='gateway/app/data/*.bak*' \
         --exclude='gateway/app/data/oauth' \
         --exclude='gateway/app/data/media' \
         --exclude='gateway/app/data/uploads' \
         --exclude='gateway/runtime/state' \
         --exclude='gateway/runtime/antigravity-home' \
         --exclude='gateway/runtime/qwen-home' \
         --exclude='*.key' \
         --exclude='*.tmp' \
         --exclude='.env*' \
         --exclude='credentials.json' \
         "$MYKOS_ROOT/" "$STAGE_DIR/opt/mykos/"

# 6. Instalar accesos directos e icono
cp "$MYKOS_ROOT/packaging/linux/mykos.desktop" "$STAGE_DIR/usr/share/applications/mykos.desktop"
cp "$MYKOS_ROOT/packaging/assets/mykos.png" "$STAGE_DIR/usr/share/icons/hicolor/512x512/apps/mykos.png"
ln -sf /opt/mykos/bin/mykos "$STAGE_DIR/usr/bin/mykos"

# 7. Compilar paquete con dpkg-deb
mkdir -p "$DIST_DIR"
echo "▶ Empaquetando con dpkg-deb..."
dpkg-deb --build --root-owner-group "$STAGE_DIR" "$DIST_DIR/${PKG_NAME}.deb"

echo "============================================================"
echo "  ✅ Paquete Debian generado con éxito:"
echo "  $DIST_DIR/${PKG_NAME}.deb"
echo "  Tamaño: $(du -h "$DIST_DIR/${PKG_NAME}.deb" | cut -f1)"
echo "============================================================"
