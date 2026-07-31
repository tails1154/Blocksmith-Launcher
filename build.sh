#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_TARGET="${1:-all}"
WINE_BUILD_PREFIX="${BLOCKSMITH_WINEPREFIX:-$PROJECT_DIR/build/wine-prefix}"
WINDOWS_PYTHON_VERSION="${BLOCKSMITH_WINDOWS_PYTHON:-3.13.7}"
WINDOWS_PYTHON_DIR='C:\Python313'
WINDOWS_PYTHON_EXE="$WINDOWS_PYTHON_DIR\\python.exe"

usage() {
  echo "Usage: ./build.sh [linux|windows|all|clean]"
  echo "Environment: BLOCKSMITH_WINEPREFIX, BLOCKSMITH_WINDOWS_PYTHON"
}

build_linux() {
  echo "Building Blocksmith for Linux..."
  local build_venv="$PROJECT_DIR/build/venv-linux"
  if [[ ! -x "$build_venv/bin/python" ]]; then
    python3 -m venv "$build_venv"
  fi
  "$build_venv/bin/python" -m pip install --upgrade pip "pyinstaller>=6.10" \
    -r "$PROJECT_DIR/requirements.txt"
  "$build_venv/bin/python" -m PyInstaller --noconfirm --clean \
    --distpath "$PROJECT_DIR/dist/linux" \
    --workpath "$PROJECT_DIR/build/pyinstaller-linux" \
    "$PROJECT_DIR/Blocksmith.spec"
  install -m 644 "$PROJECT_DIR/packaging/blocksmith.desktop" "$PROJECT_DIR/dist/linux/blocksmith.desktop"
  install -m 644 "$PROJECT_DIR/assets/blocksmith-256.png" "$PROJECT_DIR/dist/linux/blocksmith.png"
  tar -C "$PROJECT_DIR/dist/linux" -czf "$PROJECT_DIR/dist/Blocksmith-linux-x86_64.tar.gz" \
    Blocksmith blocksmith.desktop blocksmith.png
  echo "Linux build: dist/linux/Blocksmith"
}

wine_path() {
  winepath -w "$1"
}

prepare_wine_python() {
  command -v wine >/dev/null || { echo "wine is required for the Windows build" >&2; exit 1; }
  command -v curl >/dev/null || { echo "curl is required for the Windows build" >&2; exit 1; }
  mkdir -p "$WINE_BUILD_PREFIX" "$PROJECT_DIR/build/downloads"
  export WINEPREFIX="$WINE_BUILD_PREFIX"
  export WINEARCH=win64
  if [[ ! -f "$WINE_BUILD_PREFIX/system.reg" ]]; then
    echo "Creating isolated 64-bit Wine prefix: $WINE_BUILD_PREFIX"
    wineboot --init
    wineserver -w
  fi
  if ! wine "$WINDOWS_PYTHON_EXE" --version >/dev/null 2>&1; then
    local installer="$PROJECT_DIR/build/downloads/python-$WINDOWS_PYTHON_VERSION-amd64.exe"
    if [[ ! -f "$installer" ]]; then
      echo "Downloading Windows Python $WINDOWS_PYTHON_VERSION..."
      curl --fail --location --output "$installer" \
        "https://www.python.org/ftp/python/$WINDOWS_PYTHON_VERSION/python-$WINDOWS_PYTHON_VERSION-amd64.exe"
    fi
    echo "Installing Windows Python inside the isolated Wine prefix..."
    wine "$(wine_path "$installer")" /quiet InstallAllUsers=0 \
      TargetDir="$WINDOWS_PYTHON_DIR" Include_pip=1 Include_tcltk=1 Include_test=0 PrependPath=0
    wineserver -w
  fi
  wine "$WINDOWS_PYTHON_EXE" -m pip install --upgrade pip "pyinstaller>=6.10" \
    "portablemc>=4.4,<5" "platformdirs>=4.0"
}

build_windows() {
  echo "Building Blocksmith.exe using Wine..."
  prepare_wine_python
  export WINEPREFIX="$WINE_BUILD_PREFIX"
  export WINEARCH=win64
  local project_win
  local dist_win
  local work_win
  project_win="$(wine_path "$PROJECT_DIR")"
  dist_win="$(wine_path "$PROJECT_DIR/dist/windows")"
  work_win="$(wine_path "$PROJECT_DIR/build/pyinstaller-windows")"
  mkdir -p "$PROJECT_DIR/dist/windows" "$PROJECT_DIR/build/pyinstaller-windows"
  wine "$WINDOWS_PYTHON_EXE" -m PyInstaller --noconfirm --clean \
    --distpath "$dist_win" --workpath "$work_win" "$project_win\\Blocksmith.spec"
  (cd "$PROJECT_DIR/dist/windows" && zip -q -9 "$PROJECT_DIR/dist/Blocksmith-windows-x86_64.zip" Blocksmith.exe)
  echo "Windows build: dist/windows/Blocksmith.exe"
}

case "$BUILD_TARGET" in
  linux) build_linux ;;
  windows) build_windows ;;
  all) build_linux; build_windows ;;
  clean)
    rm -rf "$PROJECT_DIR/build/pyinstaller-linux" "$PROJECT_DIR/build/pyinstaller-windows" \
      "$PROJECT_DIR/dist/linux" "$PROJECT_DIR/dist/windows"
    echo "Removed generated PyInstaller outputs (Wine prefix preserved)."
    ;;
  -h|--help) usage ;;
  *) usage; exit 2 ;;
esac
