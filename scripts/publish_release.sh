#!/bin/bash
# Explicitly publish prepared artifacts as a GitHub DRAFT for final review.
set -euo pipefail
[[ $# == 2 ]] || { echo "Usage: $0 VERSION RELEASE_DIRECTORY"; exit 2; }
version=$1; folder=$(cd -- "$2" && pwd)
[[ $version =~ ^[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}$ ]] || exit 2
cd -- "$(dirname -- "$0")/.."
python3 - "$folder" "$version" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]);m=json.loads((p/'hlauncher-release.json').read_text())
if m.get('local_test'):raise SystemExit('Local test images must not be published')
if m['version']!=sys.argv[2]:raise SystemExit('Release version mismatch')
if not (p/f'HLauncher-{m["version"]}-pi4.img.xz').is_file():raise SystemExit('Fresh image missing')
if not (p/m['archive']).is_file():raise SystemExit('Update bundle missing')
PY
(cd "$folder" && sha256sum -c SHA256SUMS)
openssl pkeyutl -verify -pubin -inkey "$folder/release.pub" -rawin \
  -in "$folder/hlauncher-release.json" -sigfile "$folder/hlauncher-release.sig"
commit=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$folder/hlauncher-release.json")
gh release create "v$version" --repo evy0311/HLauncher --target "$commit" --draft \
  --title "HLauncher $version" --notes-file "$folder/RELEASE-NOTES.md" \
  "$folder"/*.xz "$folder"/*.hlu "$folder"/hlauncher-release.json "$folder"/hlauncher-release.sig \
  "$folder"/release.pub "$folder"/os-packages.txt "$folder"/SHA256SUMS "$folder"/RELEASE-NOTES.md
echo 'Draft uploaded. Review/test the release before publishing it on GitHub.'
