#!/usr/bin/env bash
# Native build only. No Apple account, signing credentials or school services.
set -euo pipefail
[[ "$(uname -s)" == Darwin ]] || { echo 'Build requires macOS.' >&2; exit 1; }
root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
python_path="${PYTHON:-python3}"
"$python_path" -c 'import platform, sys, tkinter; assert sys.version_info[:2] == (3, 13); assert platform.machine() in ("arm64", "x86_64"); tkinter.Tcl()'
[[ "$(uv --version)" == 'uv 0.12.15'* ]] || { echo 'Install uv 0.12.15.' >&2; exit 1; }
export UV_PROJECT_ENVIRONMENT="$root/build/macos/venv"
export PYTHONHASHSEED=0
export SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)"
uv sync --locked --no-dev --no-editable --python "$python_path"
python="$UV_PROJECT_ENVIRONMENT/bin/python"
uv pip install --python "$python" --no-deps \
  'pyinstaller==6.16.0' 'pyinstaller-hooks-contrib==2025.9' \
  'altgraph==0.17.4' 'macholib==1.16.3' 'setuptools==80.9.0'
uv pip check --python "$python"
"$python" packaging/macos/build_metadata.py "$root" "$root/build/macos/metadata"
# --noconfirm replaces only this native build output, never user app state.
"$python" -m PyInstaller --noconfirm --clean --distpath dist/macos \
  --workpath build/macos/pyinstaller packaging/macos/swu-checkin.spec
app="$root/dist/macos/SWUCheckin.app"
# Ad-hoc signature only; this is NOT Developer ID signing or notarization.
codesign --verify --deep --strict "$app"
"$python" - "$app" <<'PY'
import json
import pathlib
import platform
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path('packaging').resolve()))
from license_inventory import verify

app = pathlib.Path(sys.argv[1])
exe = app / 'Contents/MacOS/SWUCheckin'
assert subprocess.check_output(['lipo', '-archs', str(exe)], text=True).strip() == platform.machine()
signature = subprocess.run(['codesign', '--display', '--verbose=4', str(app)], check=True, capture_output=True, text=True)
assert 'Signature=adhoc' in signature.stderr
resources = app / 'Contents/Resources'
info = resources / 'build-info'
assert not (resources / 'LICENSE').is_symlink()
assert not info.is_symlink()
verify(info)
inventory = json.loads((info / 'LICENSE-INVENTORY.json').read_text())
for component in inventory['components']:
    for item in component['files']:
        path = info / item['path']
        assert all(not ancestor.is_symlink() for ancestor in (path, *path.parents) if ancestor.is_relative_to(info))
# A real frozen GUI and OCR model are exercised on this native CI Mac only.
subprocess.run([str(exe), '--self-test'], check=True, timeout=180)
refused = subprocess.run([str(exe), '--scheduled'], check=False, timeout=30)
assert refused.returncode == 1
PY
cp build/macos/metadata/BUILD-INFO.json dist/macos/BUILD-INFO.json
cp build/macos/metadata/LICENSE-INVENTORY.json dist/macos/LICENSE-INVENTORY.json
arch="$(uname -m)"
version="$("$python" -c 'from importlib.metadata import version; print(version("swu-checkin"))')"
archive="SWUCheckin-${version}-macos15-${arch}-preview.zip"
# ditto preserves .app symlinks and executable metadata.
ditto -c -k --sequesterRsrc --keepParent "$app" "dist/macos/$archive"
(cd dist/macos && shasum -a 256 "$archive" BUILD-INFO.json LICENSE-INVENTORY.json > SHA256SUMS.txt)
echo "Built native $arch ad-hoc-signed, unnotarized preview; no release published."
