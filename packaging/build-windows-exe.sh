#!/usr/bin/env bash
# Cross-build AutoFace.exe on Linux.
#
# PyInstaller cannot cross-compile, but it does not have to: this runs a real
# Windows CPython under Wine, so PyInstaller believes it is on Windows and
# emits a genuine PE executable. Output: dist/AutoFace.exe
#
# Native Windows (the CI job in .github/workflows/build-windows.yml) remains
# the reference build. Use this for a fast local exe without a Windows machine.
set -euo pipefail

PYTHON_VERSION="${PYTHON_VERSION:-3.11.13}"
PBS_TAG="${PBS_TAG:-20250818}"
export WINEPREFIX="${WINEPREFIX:-$HOME/.wine-autoface}"
export WINEARCH=win64
export WINEDEBUG=-all

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${WORK:-/tmp/autoface-winbuild}"
PY='C:\Python311\python.exe'

command -v wine >/dev/null || { echo "wine not installed: apt-get install wine64"; exit 1; }

mkdir -p "$WORK"

if [ ! -d "$WINEPREFIX" ]; then
  echo "==> initialising wine prefix"
  wineboot -i
fi

if [ ! -f "$WINEPREFIX/drive_c/Python311/python.exe" ]; then
  echo "==> fetching standalone Windows CPython $PYTHON_VERSION"
  # python.org is commonly blocked by egress policy; these prebuilt runtimes
  # come from GitHub release assets instead.
  curl -sSL --retry 3 -o "$WORK/winpy.tar.gz" \
    "https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PYTHON_VERSION}+${PBS_TAG}-x86_64-pc-windows-msvc-install_only.tar.gz"
  rm -rf "$WORK/winpy" && mkdir -p "$WORK/winpy"
  tar xzf "$WORK/winpy.tar.gz" -C "$WORK/winpy"
  cp -r "$WORK/winpy/python" "$WINEPREFIX/drive_c/Python311"
fi

echo "==> $(wine "$PY" --version 2>&1 | tail -1)"

echo "==> installing dependencies"
wine "$PY" -m pip install --no-warn-script-location --disable-pip-version-check -q \
  -r "$ROOT/requirements.txt" pyinstaller

echo "==> building"
cd "$ROOT"
rm -rf build dist
wine 'C:\Python311\Scripts\pyinstaller.exe' --noconfirm packaging/autoface.spec

echo "==> smoke test"
wine dist/AutoFace.exe --version

echo
echo "Built: $ROOT/dist/AutoFace.exe"
file dist/AutoFace.exe
