from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """Return a development or PyInstaller-bundled resource path."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / relative
