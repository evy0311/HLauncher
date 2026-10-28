#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
if [[ $EUID -ne 0 ]]; then
  echo 'Run: sudo bash scripts/install.sh'
  exit 1
fi
. /etc/os-release
if [[ ${VERSION_CODENAME:-} != bookworm || $(uname -m) != aarch64 ]]; then
  echo 'This installer targets Raspberry Pi OS Bookworm (64-bit).'
  exit 1
fi
apt-get update
apt-get install -y python3 python3-pil python3-dbus python3-gi \
  bluez bluez-alsa-utils libasound2-plugin-bluez alsa-utils openssl \
  nodejs npm libudev-dev libusb-1.0-0 libdrm2 libavcodec59 libavutil57 libswscale6 \
  fonts-dejavu-core fbset usbutils
root=/opt/hlauncher
if [[ $(pwd -P) == "$root" ]]; then
  echo 'Run the installer from your Git checkout, outside /opt/hlauncher.'
  exit 1
fi
stamp=$(date +%Y%m%d-%H%M%S)
if [[ -d $root ]]; then
  cp -a "$root" "/opt/hlauncher.backup-$stamp"
fi
install -d "$root" /var/log/hlauncher /var/lib/hlauncher /etc/systemd/system/bluetooth.service.d
for path in hlauncher sdk plugins examples bluetooth scripts packaging docs tests third_party LICENSE README.md THIRD_PARTY_NOTICES.md; do
  cp -a "$path" "$root/"
done
npm ci --prefix "$root/plugins/carplay/runtime/usb" --omit=dev --ignore-scripts --no-audit --no-fund
if [[ ! -f /etc/hlauncher.env ]]; then
  install -m 600 hlauncher.env.example /etc/hlauncher.env
fi
for unit in hlauncher.service hlauncher-audio.service hlauncher-connect.service; do
  install -m 644 "packaging/$unit" "/etc/systemd/system/$unit"
done
dropin=/etc/systemd/system/bluetooth.service.d/90-hlauncher.conf
if [[ -f $dropin ]]; then cp -a "$dropin" "$dropin.backup-$stamp"; fi
install -m 644 packaging/90-hlauncher.conf "$dropin"
systemctl daemon-reload
/usr/bin/python3 "$root/scripts/check.py"
echo
echo 'Installed. No HLauncher services were started.'
echo 'Follow docs/setup.md to pair the radio, set its address and start HLauncher.'
