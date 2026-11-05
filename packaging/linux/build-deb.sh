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
Depends: nodejs (>= 20.0.0), python3 (>= 3.10), python3-pip, python3-venv, curl, bash
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
chmod +x /opt/mykos/bin/mykos
ln -sf /opt/mykos/bin/mykos /usr/bin/mykos

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi

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
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
  fi
fi
exit 0
EOF
chmod 755 "$STAGE_DIR/DEBIAN/postrm"

# 5. Copiar ficheros del proyecto a /opt/mykos
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
