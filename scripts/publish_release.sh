#!/bin/bash
# Explicitly publish prepared artifacts as a GitHub DRAFT for final review.
set -euo pipefail
[[ $# == 2 ]] || { echo "Usage: $0 VERSION RELEASE_DIRECTORY"; exit 2; }
version=$1; folder=$(cd -- "$2" && pwd)
[[ $version =~ ^[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}$ ]] || exit 2
cd -- "$(dirname -- "$0")/.."
notes="$folder/RELEASE-NOTES.md"
[[ -s $notes ]] || { echo 'Supply release notes for the GitHub description.'; exit 1; }
# Upload the same asset list that passed checksum and signature validation.
names=$(python3 scripts/validate_release.py "$version" "$folder")
assets=()
while IFS= read -r name; do
  assets+=("$folder/$name")
done <<< "$names"
commit=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$folder/hlauncher-release.json")
gh release create "v$version" --repo evy0311/HLauncher --target "$commit" --draft \
  --title "HLauncher $version" --notes-file "$notes" "${assets[@]}"
echo 'Draft uploaded. Review/test the release before publishing it on GitHub.'
