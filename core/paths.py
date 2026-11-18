"""Shared application-root resolution.

Returns the directory the app's data folders (actions/, plugins/, config/…)
live beside: the executable's folder when running from a PyInstaller bundle,
otherwise the repository root.
"""
from __future__ import annotations

import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent
