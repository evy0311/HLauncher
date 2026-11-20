#!/bin/bash
# Publish validated releases as drafts; opt-in development snapshots may publish directly.
set -euo pipefail
publish_development=false
if [[ ${1:-} == --publish-development ]]; then publish_development=true; shift; fi
[[ $# == 2 ]] || { echo "Usage: $0 [--publish-development] VERSION RELEASE_DIRECTORY"; exit 2; }
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
channel=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("channel","stable"))' "$folder/hlauncher-release.json")
flags=(--draft)
tag="v$version"
[[ $publish_development == false || $channel == development ]] || { echo 'Only development snapshots can use automatic publication.'; exit 1; }
title="HLauncher $version"
if [[ $channel == beta ]]; then
  git merge-base --is-ancestor "$commit" refs/remotes/origin/develop || {
    echo 'Fetch origin and push the beta source commit to develop before uploading.'
    exit 1
  }
  flags+=(--prerelease --latest=false)
  title="HLauncher $version Beta"
fi
if [[ $channel == development ]]; then
  tag="dev-$version"
  branch=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["branch"])' "$folder/hlauncher-release.json")
  flags+=(--prerelease --latest=false)
  if [[ $publish_development == true ]]; then flags=(--prerelease --latest=false); fi
  title="Development: $branch ($version)"
fi
gh release create "$tag" --repo evy0311/HLauncher --target "$commit" \
  "${flags[@]}" --title "$title" --notes-file "$notes" "${assets[@]}"
if [[ $publish_development == true ]]; then echo 'Development snapshot published.'; else echo 'Draft uploaded. Review/test the release before publishing it on GitHub.'; fi
