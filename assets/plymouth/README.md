# MyCOS Plymouth — 2026-10-16

Fuentes comprobadas: Lenovo procede de /sys/firmware/acpi/bgrt/image (768×432, status 1); copia visual firmware-bgrt.png. El tema activo previo era zorin-logo, módulo two-step con UseFirmwareBackground=true. Zorin está dibujado en los 39 throbber-*.png y 37 animation-*.png; no hay logo/spinner separado. Evidencia visual: zorin-frames.png.

Tema propio: /usr/share/plymouth/themes/mycos-logo. Se conserva módulo, layout, fondo Lenovo, prompts, recursos de contraseña, texto fallback y configuración. Los 76 frames contienen ahora la MISMA imagen MyCOS estática: sin vídeo, nueva animación ni reproducción. El Z animado preexistente se sustituye también para que no siga apareciendo Zorin. Canvas original 556×140, logo 245×84 proporcional RGBA transparente, fuente assets/intro/logo-mycos-azul.png (2141×734). Preview mycos-static-preview.png.

Selección manual default.plymouth; prioridad 190 (Zorin original 200, sin alterar). Esclavo default.grub idéntico al original. No se ejecuta update-grub. Solo update-initramfs -u -k 7.0.0-38-generic. Kernel antiguo 6.14.0-33-generic e imágenes vmlinuz conservados, verificación SHA256 en backup.

Backup root: /var/backups/plymouth-mycos-20261016/ incluye initrd anterior completo, tema original, alternativas previas, hashes y rollback.sh. Reversión con autorización administrativa:

    pkexec /bin/bash /var/backups/plymouth-mycos-20261016/rollback.sh

Restaura selección automática Zorin e initramfs exacto anterior; conserva tema MyCOS sin seleccionarlo. No modifica firmware, EFI, particiones, instalación bootloader, kernel, audio, autostart, snap ni gateway.

Discos verificados: / en sda5 USB; /boot en sda2 USB (275 MiB libres previos); /boot/efi en nvme0n1p1. No se reinicia ni se reproduce Plymouth sobre la sesión gráfica. Comprobación visual del próximo arranque real queda pendiente.
