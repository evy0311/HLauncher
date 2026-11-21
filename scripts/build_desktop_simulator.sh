#!/bin/bash
# Build a small native wrapper. Python and the UI remain in this live checkout.
set -euo pipefail
sim_repo="$(cd "$(dirname "$0")/.." && pwd)"
sim_python="${HLAUNCHER_SIMULATOR_PYTHON:-$(command -v python3)}"
sim_app="$sim_repo/build/HLauncher Simulator.app"
"$sim_python" -c 'import PIL, numpy, cryptography' || { echo 'Install desktop dependencies: python3 -m pip install -r tools/desktop_simulator/requirements.txt' >&2; exit 1; }
mkdir -p "$sim_app/Contents/MacOS" "$sim_app/Contents/Resources"
swiftc -module-cache-path "$sim_repo/build/desktop-module-cache" "$sim_repo/tools/desktop_simulator/MacApp.swift" -o "$sim_app/Contents/MacOS/HLauncherSimulator" -framework AppKit -framework WebKit
"$sim_python" - "$sim_app" "$sim_repo" "$sim_python" <<'PY'
import json,os,plistlib,sys
from pathlib import Path
app,repo,python=sys.argv[1:]
config=dict(repo=repo,python=os.path.abspath(python))
if os.environ.get('HLAUNCHER_SIMULATOR_STATE'):config['state']=os.environ['HLAUNCHER_SIMULATOR_STATE']
root=Path(app)/'Contents'
(root/'Resources/simulator.json').write_text(json.dumps(config))
with (root/'Info.plist').open('wb') as f:
 plistlib.dump(dict(CFBundleName='HLauncher Simulator',CFBundleDisplayName='HLauncher Simulator',
  CFBundleIdentifier='dev.hlauncher.desktop-simulator',CFBundleVersion='1',CFBundleShortVersionString='1.0',
  CFBundleExecutable='HLauncherSimulator',CFBundlePackageType='APPL',NSHighResolutionCapable=True,
  NSAppTransportSecurity=dict(NSAllowsLocalNetworking=True)),f)
PY
printf 'Built %s\nOpen it with: open "%s"\n' "$sim_app" "$sim_app"
