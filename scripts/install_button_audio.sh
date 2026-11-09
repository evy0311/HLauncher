#!/bin/bash
# Keep the distro daemon intact. Build the pinned BlueALSA with proxy VR features.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run sudo bash scripts/install_button_audio.sh'; exit 1; }
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
prefix=/opt/hlauncher-deps
source_dir=$prefix/src/bluealsa-buttons
revision=dd05a1baa261b94da9ba977b5e3392c8b4dc7a5e
apt-get update
apt-get install -y git autoconf automake libtool pkg-config build-essential \
  libasound2-dev libbluetooth-dev libdbus-1-dev libglib2.0-dev libsbc-dev libldacbt-enc-dev libldacbt-abr-dev
if [[ ! -d $source_dir/.git ]]; then
  [[ ! -e $source_dir ]] || { echo 'Unexpected existing source directory'; exit 1; }
  git init "$source_dir"
  git -C "$source_dir" remote add origin https://github.com/arkq/bluez-alsa.git
  git -C "$source_dir" fetch --depth=1 origin "$revision"
  git -C "$source_dir" checkout --detach FETCH_HEAD
fi
[[ $(git -C "$source_dir" rev-parse HEAD) == "$revision" ]] || exit 1
python3 "$root/scripts/patch_button_audio.py" "$source_dir/src/bluealsa-config.c"
python3 "$root/scripts/patch_call_audio.py" "$source_dir/src/ba-rfcomm.c"
cd "$source_dir"
autoreconf --install
./configure --prefix="$prefix/bluealsa-buttons" --disable-aplay --disable-cli \
  --disable-rfcomm --enable-ldac --enable-ldac-abr
make -j2
# Only install the daemon. ALSA plugins, DBus policy, and system binary remain packaged versions.
install -Dm755 src/bluealsa "$prefix/bluealsa-buttons/bin/bluealsa"
echo 'Built button-aware BlueALSA; services were not changed.'
