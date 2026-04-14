"""
Path helpers that work in both dev mode and PyInstaller frozen mode.

- get_data_dir()   → read-only bundled data (sprites, etc.)
- get_config_dir() → writable location for config.json (next to .exe when frozen)
"""

import os
import sys


def is_frozen() -> bool:
    """Return True when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def get_data_dir() -> str:
    """Return the root directory for read-only data (sprites, etc.).

    - Dev mode:    project root  (parent of utils/)
    - Frozen mode: sys._MEIPASS  (_internal folder created by PyInstaller)
    """
    if is_frozen():
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_config_dir() -> str:
    """Return the directory for writable config files.

    - Dev mode:    project root
    - Frozen mode: directory containing the .exe
    """
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_writable_sprites_dir() -> str:
    """Return the writable sprites directory (next to .exe when frozen, project root in dev).

    Downloaded character packs are stored here.  In dev mode this is the
    same as the bundled sprites dir; in frozen mode it sits next to the
    executable so it persists across updates.
    """
    return os.path.join(get_config_dir(), "sprites")
