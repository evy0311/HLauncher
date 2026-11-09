#!/bin/bash
# Explicitly publish prepared artifacts as a GitHub DRAFT for final review.
set -euo pipefail
[[ $# == 2 ]] || { echo "Usage: $0 VERSION RELEASE_DIRECTORY"; exit 2; }
version=$1; folder=$(cd -- "$2" && pwd)
[[ $version =~ ^[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}$ ]] || exit 2
cd -- "$(dirname -- "$0")/.."
# Validate all files, checksums and signature before creating anything on GitHub.
python3 scripts/validate_release.py "$version" "$folder" >/dev/null
commit=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$folder/hlauncher-release.json")
gh release create "v$version" --repo evy0311/HLauncher --target "$commit" --draft \
  --title "HLauncher $version" --notes-file "$folder/RELEASE-NOTES.md" \
  "$folder/HLauncher-$version-pi4.img.xz" "$folder/HLauncher-$version-pi4-arm64.tar.xz" \
  "$folder/HLauncher-$version-local-update.hlu" "$folder/HLauncher-$version-sources.tar.xz" "$folder"/hlauncher-release.json "$folder"/hlauncher-release.sig \
  "$folder"/release.pub "$folder"/os-packages.txt "$folder"/SHA256SUMS "$folder"/RELEASE-NOTES.md
echo 'Draft uploaded. Review/test the release before publishing it on GitHub.'
