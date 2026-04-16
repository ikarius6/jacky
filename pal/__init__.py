# -*- coding: utf-8 -*-
"""Platform Abstraction Layer — public API.

Usage::

    from pal import backend, WindowInfo
    windows = backend.get_visible_windows()

The singleton ``backend`` is created once on first import based on
``sys.platform``.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from pal.base import (
    PlatformBackend,
    WindowInfo,
    EVENT_OBJECT_CREATE,
    EVENT_OBJECT_DESTROY,
    EVENT_OBJECT_SHOW,
)

if TYPE_CHECKING:
    pass  # future: conditional type imports

# ── Singleton backend ────────────────────────────────────────────────────────


def _create_backend() -> PlatformBackend:
    if sys.platform == "win32":
        from pal.windows import WindowsBackend
        return WindowsBackend()
    elif sys.platform == "darwin":
        # Phase 2: from pal.macos import MacOSBackend
        raise NotImplementedError("macOS backend not yet implemented")
    else:
        raise NotImplementedError(f"Unsupported platform: {sys.platform}")


backend: PlatformBackend = _create_backend()


# ── Convenience re-exports (backward-compatible function names) ──────────────
# These let consumer code do ``from pal import click_at`` instead of
# ``from pal import backend; backend.click_at(...)``.

get_screen_size = backend.get_screen_size
get_work_area = backend.get_work_area
get_taskbar_rect = backend.get_taskbar_rect
get_visible_windows = backend.get_visible_windows
get_foreground_window = backend.get_foreground_window
move_window = backend.move_window
set_window_pos = backend.set_window_pos
resize_window = backend.resize_window
minimize_window = backend.minimize_window
flash_window = backend.flash_window
set_foreground_window = backend.set_foreground_window
tile_windows = backend.tile_windows
get_window_rect = backend.get_window_rect
set_topmost = backend.set_topmost
get_cursor_position = backend.get_cursor_position
set_cursor_position = backend.set_cursor_position
click_at = backend.click_at
minimize_foreground_window = backend.minimize_foreground_window
type_text = backend.type_text
get_power_status = backend.get_power_status
get_idle_seconds = backend.get_idle_seconds
register_window_event_hook = backend.register_window_event_hook
unregister_all_hooks = backend.unregister_all_hooks

# Backward-compat aliases (old function names → new generic names)
send_alt_f4 = backend.send_close_window
remove_dwm_border = backend.remove_window_border
set_window_click_through = backend.set_click_through

__all__ = [
    "backend",
    "PlatformBackend",
    "WindowInfo",
    "EVENT_OBJECT_CREATE",
    "EVENT_OBJECT_DESTROY",
    "EVENT_OBJECT_SHOW",
    # convenience re-exports
    "get_screen_size",
    "get_work_area",
    "get_taskbar_rect",
    "get_visible_windows",
    "get_foreground_window",
    "move_window",
    "set_window_pos",
    "resize_window",
    "minimize_window",
    "flash_window",
    "set_foreground_window",
    "tile_windows",
    "get_window_rect",
    "set_topmost",
    "get_cursor_position",
    "set_cursor_position",
    "click_at",
    "minimize_foreground_window",
    "type_text",
    "get_power_status",
    "get_idle_seconds",
    "register_window_event_hook",
    "unregister_all_hooks",
    # backward-compat aliases
    "send_alt_f4",
    "remove_dwm_border",
    "set_window_click_through",
]
