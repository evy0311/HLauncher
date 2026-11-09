#!/bin/bash
# Produce the image, signed updater bundle, sources and SHA256SUMS from one build.
set -euo pipefail
if [[ $# != 5 ]]; then
  echo "Usage: sudo $0 VERSION BASE.img WIFI_COUNTRY ED25519_PRIVATE_KEY OUTPUT_DIRECTORY"; exit 2
fi
version=$1; base=$2; country=$3; key=$4; output=$5
[[ $version =~ ^[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}$ ]] || { echo 'Use a stable version such as 0.2.0'; exit 1; }
[[ $EUID == 0 && $(uname -s) == Linux && $(uname -m) == aarch64 ]] || { echo 'Use an ARM64 Linux host as root.'; exit 1; }
source_root=$(cd -- "$(dirname -- "$0")/.." && pwd)
cd "$source_root"
[[ -z $(git status --porcelain) ]] || { echo 'Commit your release source first; the working tree must be clean.'; exit 1; }
for tool in openssl xz sha256sum git; do command -v "$tool" >/dev/null; done
[[ -f $key && ! -e $output ]] || { echo 'Supply an external signing key and a new output directory.'; exit 1; }
key=$(realpath "$key"); output=$(realpath -m "$output")
[[ $key != "$source_root/"* ]] || { echo 'Keep signing keys outside the repository.'; exit 1; }
mkdir -p "$output"
export HLAUNCHER_RELEASE_VERSION="$version" HLAUNCHER_RELEASE_KEY="$key" HLAUNCHER_RELEASE_OUTPUT="$output"
export HLAUNCHER_RELEASE_COMMIT=$(git rev-parse HEAD)
bash scripts/build_image.sh "$base" "$output/HLauncher-$version-pi4.img" "$country"
xz -T0 "$output/HLauncher-$version-pi4.img"
rm "$output/HLauncher-$version-pi4.img.sha256"
cat > "$output/RELEASE-NOTES.md" <<EOF
HLauncher $version

Source commit: $HLAUNCHER_RELEASE_COMMIT
Platform: Raspberry Pi 4, ARM64, Raspberry Pi OS Bookworm
Local test SSH image: ${HLAUNCHER_LOCAL_TEST_SSH_KEY:+YES - DO NOT PUBLISH}

Fresh install: flash HLauncher-$version-pi4.img.xz with Raspberry Pi Imager.
Existing update-enabled images: Settings > System > Software updates.
The signed update bundle keeps settings, pairing and user plugins, and retains
one previous installed version for manual restore. OS/platform contract changes
require a new image or a separately validated system migration.

The source archive includes the HLauncher build tree and fetched external sources.
See THIRD_PARTY_NOTICES.md inside it for dependency licenses and source origins.
Validate this image from fresh setup on a spare SD card before publishing.
EOF
(cd "$output" && sha256sum ./*.xz ./*.hlu ./*.json ./*.sig ./*.pub ./*.txt > SHA256SUMS)
echo "Release artifacts: $output"
echo "Test them, then: bash scripts/publish_release.sh $version $output"
