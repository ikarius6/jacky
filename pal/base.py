# -*- coding: utf-8 -*-
"""Platform Abstraction Layer — abstract base & shared types."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from typing import Any, Callable, List, Optional, Tuple

log = logging.getLogger("pal.base")


# ── Shared data types ────────────────────────────────────────────────────────

class WindowInfo:
    """Lightweight snapshot of a visible desktop window."""
    __slots__ = ("hwnd", "title", "rect", "is_maximized", "is_minimized", "process_name")

    def __init__(self, hwnd: int, title: str, rect: Tuple[int, int, int, int],
                 is_maximized: bool, is_minimized: bool, process_name: str = ""):
        self.hwnd = hwnd
        self.title = title
        self.rect = rect  # (left, top, right, bottom)
        self.is_maximized = is_maximized
        self.is_minimized = is_minimized
        self.process_name = process_name

    @property
    def left(self) -> int:
        return self.rect[0]

    @property
    def top(self) -> int:
        return self.rect[1]

    @property
    def right(self) -> int:
        return self.rect[2]

    @property
    def bottom(self) -> int:
        return self.rect[3]

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]

    @property
    def title_bar_rect(self) -> Tuple[int, int, int, int]:
        """Approximate title bar region: full width, ~32px tall from top."""
        title_bar_h = 32
        return (self.left, self.top, self.right, self.top + title_bar_h)


# ── WinEvent constants (cross-platform stubs) ────────────────────────────────

EVENT_OBJECT_CREATE  = 0x8000
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW    = 0x8002


# ── Abstract backend ─────────────────────────────────────────────────────────

class PlatformBackend(ABC):
    """Interface that each OS backend must implement."""

    # -- Screen / desktop geometry -----------------------------------------

    @abstractmethod
    def get_screen_size(self) -> Tuple[int, int]:
        """Return (width, height) of the primary screen in logical pixels."""

    @abstractmethod
    def get_work_area(self) -> Tuple[int, int, int, int]:
        """Return (left, top, right, bottom) of the usable desktop area."""

    @abstractmethod
    def get_taskbar_rect(self) -> Tuple[int, int, int, int]:
        """Return (left, top, right, bottom) of the OS taskbar/dock."""

    # -- Window enumeration ------------------------------------------------

    @abstractmethod
    def get_visible_windows(self, exclude_pids: Optional[set] = None) -> List[WindowInfo]:
        """Return a list of all visible, non-cloaked desktop windows."""

    @abstractmethod
    def get_foreground_window(self) -> Optional[WindowInfo]:
        """Return the currently focused window, or *None*."""

    # -- Window manipulation -----------------------------------------------

    @abstractmethod
    def move_window(self, wid: int, dx: int, dy: int) -> bool:
        """Nudge a window by *(dx, dy)* pixels.  Returns success."""

    @abstractmethod
    def set_window_pos(self, wid: int, x: int, y: int) -> bool:
        """Move a window to absolute *(x, y)*.  Returns success."""

    @abstractmethod
    def resize_window(self, wid: int, dw: int, dh: int) -> bool:
        """Grow/shrink a window by *(dw, dh)*.  Returns success."""

    @abstractmethod
    def minimize_window(self, wid: int) -> bool:
        """Minimize a window.  Returns success."""

    @abstractmethod
    def flash_window(self, wid: int, count: int = 3) -> bool:
        """Flash a window's taskbar button.  Returns success."""

    @abstractmethod
    def set_foreground_window(self, wid: int) -> bool:
        """Bring a window to the foreground.  Returns success."""

    @abstractmethod
    def tile_windows(self, wids: List[int]) -> bool:
        """Tile the given windows side-by-side.  Returns success."""

    @abstractmethod
    def get_window_rect(self, wid: int) -> Optional[Tuple[int, int, int, int]]:
        """Return (left, top, right, bottom) of a window, or *None*."""

    # -- Pet-window chrome -------------------------------------------------

    @abstractmethod
    def set_topmost(self, wid: int) -> None:
        """Force a window to stay above all others."""

    @abstractmethod
    def remove_window_border(self, wid: int) -> None:
        """Remove OS-drawn shadow / border around a window."""

    @abstractmethod
    def set_click_through(self, wid: int, enabled: bool) -> bool:
        """Make a window transparent to mouse clicks (or restore)."""

    # -- Cursor / input simulation -----------------------------------------

    @abstractmethod
    def get_cursor_position(self) -> Tuple[int, int]:
        """Return current cursor (x, y) in screen coords."""

    @abstractmethod
    def set_cursor_position(self, x: int, y: int) -> bool:
        """Move the cursor to *(x, y)*.  Returns success."""

    @abstractmethod
    def click_at(self, x: int, y: int, safety_check: bool = True) -> bool:
        """Simulate a left-click at *(x, y)*.  Returns success."""

    @abstractmethod
    def send_close_window(self) -> bool:
        """Send the OS close-window shortcut (Alt+F4 / Cmd+W)."""

    @abstractmethod
    def minimize_foreground_window(self) -> bool:
        """Minimize whichever window is currently in the foreground."""

    @abstractmethod
    def type_text(self, text: str, char_delay: float = 0.02) -> bool:
        """Type *text* via synthetic keyboard input.  Returns success."""

    # -- System information ------------------------------------------------

    @abstractmethod
    def get_power_status(self) -> Tuple[bool, int]:
        """Return *(ac_online, battery_percent)*.

        *battery_percent* is 0–100, or -1 if unknown.
        """

    @abstractmethod
    def get_idle_seconds(self) -> float:
        """Seconds since the last user input event."""

    # -- Global hotkey -----------------------------------------------------

    @abstractmethod
    def validate_shortcut(self, shortcut: str) -> None:
        """Raise *ValueError* if *shortcut* is not parseable on this OS."""

    @abstractmethod
    def register_hotkey(self, shortcut: str, key_id: int,
                        callback: Callable) -> Optional[Any]:
        """Register a global hotkey.  Returns a handle (or *None* on failure)."""

    @abstractmethod
    def unregister_hotkey(self, handle: Any) -> None:
        """Unregister a previously registered global hotkey."""

    # -- Window-event hooks ------------------------------------------------

    @abstractmethod
    def register_window_event_hook(self, callback: Callable) -> None:
        """Start receiving window create/destroy/show events via *callback*."""

    @abstractmethod
    def unregister_all_hooks(self) -> None:
        """Remove all window-event hooks registered by this backend."""
