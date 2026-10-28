#!/bin/bash
# Build the external OpenAuto engine. Does not replace the OS or restart HLauncher.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
if [[ $EUID -ne 0 ]]; then echo 'Run sudo bash scripts/install_android_auto.sh'; exit 1; fi
prefix=/opt/hlauncher-deps
apt-get update
apt-get install -y git cmake g++ pkg-config libboost-system-dev libboost-log-dev \
  libusb-1.0-0-dev libprotobuf-dev protobuf-compiler libssl-dev qtbase5-dev libabsl-dev
prepare() {
  local name=$1 url=$2 commit=$3
  local path="$prefix/src/$name"
  if [[ ! -d "$path/.git" ]]; then
    if [[ -e "$path" ]]; then echo "Existing non-Git source at $path; preserve or move it before reinstalling."; exit 1; fi
    git init "$path"
    git -C "$path" remote add origin "$url"
    git -C "$path" fetch --depth=1 origin "$commit"
    git -C "$path" checkout --detach FETCH_HEAD
  fi
  [[ $(git -C "$path" rev-parse HEAD) == "$commit" ]] || { echo "Unexpected $name revision"; exit 1; }
}
mkdir -p "$prefix/src" "$prefix/build"
prepare aasdk https://github.com/opencardev/aasdk.git 9bf6adf933665dee26532201719fac14a047ccf1
prepare openauto https://github.com/opencardev/openauto.git 4cc739b813622739b09352655581072fc4d39280
apply_patch() {
  local name=$1 patch_file="$(pwd)/third_party/patches/$1.patch"
  if git -C "$prefix/src/$name" apply --reverse --check "$patch_file" 2>/dev/null; then
    echo "$name integration patch already applied"
  else
    git -C "$prefix/src/$name" diff --quiet || { echo "External $name source has unrecognized changes"; exit 1; }
    git -C "$prefix/src/$name" apply "$patch_file"
  fi
}
apply_patch aasdk
apply_patch openauto
cmake -S "$prefix/src/aasdk" -B "$prefix/build/aasdk" -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$prefix" -DSKIP_BUILD_PROTOBUF=ON -DSKIP_BUILD_ABSL=ON \
  -DAASDK_TEST=OFF -DDISABLE_MODERN_LOGGING=ON
cmake --build "$prefix/build/aasdk" -j"${HLAUNCHER_BUILD_JOBS:-2}"
cmake --install "$prefix/build/aasdk"
cmake -S plugins/android-auto/native -B "$prefix/build/hlauncher" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix" -DDEPS="$prefix"
cmake --build "$prefix/build/hlauncher" -j"${HLAUNCHER_BUILD_JOBS:-2}"
cmake --install "$prefix/build/hlauncher"
"$prefix/bin/hlauncher-android-auto" --check
printf '\nOpenAuto installed. Reopen the Android Auto plugin in HLauncher.\n'
