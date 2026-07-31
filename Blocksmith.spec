# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

project_root = Path(SPECPATH)
windows = sys.platform == "win32"
icon = project_root / "assets" / ("blocksmith.ico" if windows else "blocksmith-256.png")

a = Analysis(
    [str(project_root / "run.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(project_root / "assets" / "blocksmith-256.png"), "assets")],
    hiddenimports=["portablemc", "portablemc.auth", "portablemc.fabric", "portablemc.forge", "portablemc.standard"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Blocksmith",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon),
)
