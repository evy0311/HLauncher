#!/bin/bash
# Produce the image, signed updater bundle, sources and SHA256SUMS from one build.
set -euo pipefail
if [[ $# != 6 ]]; then
  echo "Usage: sudo $0 VERSION BASE.img WIFI_COUNTRY ED25519_PRIVATE_KEY OUTPUT_DIRECTORY RELEASE_NOTES.md"; exit 2
fi
version=$1; base=$2; country=$3; key=$4; output=$5; notes=$(realpath "$6")
[[ -s $notes ]] || { echo 'Supply short release notes: changes since the previous release and essential compatibility information.'; exit 1; }
[[ -z ${HLAUNCHER_LOCAL_TEST_SSH_KEY:-} ]] || { echo 'Public releases must not include developer SSH access.'; exit 1; }
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
cp "$notes" "$output/RELEASE-NOTES.md"
(cd "$output" && sha256sum HLauncher-"$version"-*.xz "HLauncher-$version-local-update.hlu" \
  hlauncher-release.json hlauncher-release.sig release.pub os-packages.txt RELEASE-NOTES.md > SHA256SUMS)
python3 scripts/validate_release.py "$version" "$output" >/dev/null
echo "Release artifacts: $output"
echo "Test them, then: bash scripts/publish_release.sh $version $output"
