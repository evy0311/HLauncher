#!/bin/bash
# Build a NEW image from a pristine, uncompressed Raspberry Pi OS Lite Bookworm arm64 image.
set -euo pipefail
if [[ $# != 3 ]]; then echo "Usage: sudo $0 BASE.img OUTPUT.img WIFI_COUNTRY"; exit 2; fi
[[ $EUID == 0 && $(uname -s) == Linux ]] || { echo 'Use a Linux build host as root.'; exit 1; }
base=$(realpath "$1"); output=$(realpath -m "$2"); country=$3
[[ -f $base && ! -e $output && $country =~ ^[A-Z]{2}$ ]] || { echo 'Use an existing base, a new output path and a two-letter country.'; exit 1; }
source_root=$(cd -- "$(dirname -- "$0")/.." && pwd)
for tool in losetup parted partprobe udevadm e2fsck resize2fs mkfs.ext4 blkid chroot python3; do command -v "$tool" >/dev/null; done
[[ $(uname -m) == aarch64 ]] || { echo 'This build currently requires an arm64 Linux host (or arm64 VM).'; exit 1; }
cp --reflink=auto -- "$base" "$output"
size=$(stat -c %s "$output")
# Add 3 GiB root space plus a 512 MiB persistent data partition.
root_end=$(( (size + 3221225472) / 1048576 ))
truncate -s "$(( (root_end + 512) * 1048576 ))" "$output"
loop=$(losetup --find --show --partscan "$output")
work=$(mktemp -d)
cleanup() {
  for path in "$work/root/dev" "$work/root/proc" "$work/root/sys" "$work/root/boot/firmware" "$work/root/boot" "$work/persist" "$work/root"; do
    mountpoint -q "$path" && umount -R "$path" || true
  done
  losetup -d "$loop" || true
  rm -rf -- "$work"
}
trap cleanup EXIT
[[ $(lsblk -ln -o TYPE "$loop" | grep -c part) == 2 ]] || { echo 'Base must have exactly boot + ext4 root partitions.'; exit 1; }
parted -s "$loop" resizepart 2 "${root_end}MiB"
parted -s "$loop" mkpart primary ext4 "${root_end}MiB" 100%
partprobe "$loop"; udevadm settle
# e2fsck exit 1 means corrected errors, not failure.
e2fsck -pf "${loop}p2" || [[ $? == 1 ]]
resize2fs "${loop}p2"
mkfs.ext4 -q -L HLAUNCHER_STATE "${loop}p3"
mkdir -p "$work/root" "$work/persist"
mount "${loop}p2" "$work/root"
[[ ! -e $work/root/opt/hlauncher && -z $(find "$work/root/home" -mindepth 1 -maxdepth 1 -print -quit) ]] || {
  echo 'Use a pristine official OS image, not an existing personal installation.'; exit 1;
}
mount "${loop}p3" "$work/persist"
boot="$work/root/boot/firmware"; [[ -d $boot ]] || boot="$work/root/boot"
mount "${loop}p1" "$boot"
for dir in dev proc sys; do mount --rbind "/$dir" "$work/root/$dir"; mount --make-rslave "$work/root/$dir"; done
# Block package-triggered service starts inside the image build.
policy="$work/root/usr/sbin/policy-rc.d"
[[ ! -e $policy ]] || cp -a "$policy" "$work/policy-rc.d"
printf '#!/bin/sh\nexit 101\n' > "$policy"; chmod 755 "$policy"
# Supply build DNS without following a guest symlink into the host filesystem.
if [[ -e $work/root/etc/resolv.conf || -L $work/root/etc/resolv.conf ]]; then
  cp -a "$work/root/etc/resolv.conf" "$work/resolv.conf"
fi
rm -f "$work/root/etc/resolv.conf"
cp -L /etc/resolv.conf "$work/root/etc/resolv.conf"
mkdir -p "$work/root/tmp/hlauncher-source"
for path in hlauncher sdk plugins examples bluetooth scripts packaging config docs tests third_party native LICENSE NOTICE README.md THIRD_PARTY_NOTICES.md hlauncher.env.example; do
  cp -a "$source_root/$path" "$work/root/tmp/hlauncher-source/"
done
# Host-side npm caches/vendor downloads are excluded; installer fetches locked dependencies.
find "$work/root/tmp/hlauncher-source" -type d \( -name node_modules -o -name __pycache__ \) -prune -exec rm -rf {} +
chroot "$work/root" /bin/bash /tmp/hlauncher-source/scripts/install.sh
chroot "$work/root" /bin/bash /tmp/hlauncher-source/scripts/install_android_auto.sh
if [[ -e $work/policy-rc.d ]]; then cp -a "$work/policy-rc.d" "$policy"; else rm "$policy"; fi
rm -rf "$work/root/tmp/hlauncher-source"
rm -f "$work/root/etc/resolv.conf"
if [[ -e $work/resolv.conf || -L $work/resolv.conf ]]; then cp -a "$work/resolv.conf" "$work/root/etc/resolv.conf"; fi
state_uuid=$(blkid -s UUID -o value "${loop}p3")
python3 "$source_root/scripts/prepare_image.py" --root "$work/root" --persist "$work/persist" --state-uuid "$state_uuid" --country "$country"
sync
cleanup
trap - EXIT
sha256sum "$output" > "$output.sha256"
echo "Built $output; validate on a Pi before distributing."
