#!/bin/bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
k="$(uname -r)"
src="$SCRIPT_DIR/mycos-logo"
dst=/usr/share/plymouth/themes/mycos-logo
old=/usr/share/plymouth/themes/zorin-logo/zorin-logo.plymouth
backup=/var/backups/plymouth-mycos-20261016
[ "$(id -u)" = 0 ]
[ "$(uname -r)" = "$k" ]
[ "$(readlink -f /usr/share/plymouth/themes/default.plymouth)" = "$old" ]
[ ! -e "$dst" ]; [ ! -e "$backup" ]
[ "$(df --output=avail -B1 /boot | tail -1)" -gt 180000000 ]
mkdir -m 700 "$backup"
cp -a /boot/initrd.img-$k "$backup/"
cp -a /usr/share/plymouth/themes/zorin-logo "$backup/"
cp -a /var/lib/dpkg/alternatives/default.plymouth "$backup/default.plymouth.alternatives"
update-alternatives --query default.plymouth > "$backup/alternatives-before.txt"
sha256sum /boot/initrd.img-6.14.0-33-generic /boot/vmlinuz-* > "$backup/recovery-kernels.sha256"
cat > "$backup/rollback.sh" <<'ROLLBACK'
#!/bin/bash
set -euo pipefail
update-alternatives --remove default.plymouth /usr/share/plymouth/themes/mycos-logo/mycos-logo.plymouth
update-alternatives --auto default.plymouth
cp -a /var/backups/plymouth-mycos-20261016/initrd.img-7.0.0-38-generic /boot/initrd.img-7.0.0-38-generic.mycos-restore
mv -f /boot/initrd.img-7.0.0-38-generic.mycos-restore /boot/initrd.img-7.0.0-38-generic
sync
ROLLBACK
chmod 700 "$backup/rollback.sh"
trap 'echo "Installation failed; restoring prior selection and initramfs"; bash "$backup/rollback.sh"' ERR
cp -a "$src" "$dst"
chown -R root:root "$dst"
update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth "$dst/mycos-logo.plymouth" 190 --slave /usr/share/plymouth/themes/default.grub default.plymouth.grub "$dst/mycos-logo.grub"
update-alternatives --set default.plymouth "$dst/mycos-logo.plymouth"
update-initramfs -u -k "$k"
sha256sum -c "$backup/recovery-kernels.sha256"
lsinitramfs /boot/initrd.img-$k > "$backup/initramfs-files.txt"
grep -q 'usr/share/plymouth/themes/mycos-logo/mycos-logo.plymouth' "$backup/initramfs-files.txt"
update-alternatives --query default.plymouth
sync
echo "MYCOS_INSTALL_VERIFIED backup=$backup"
