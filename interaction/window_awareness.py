import random
from typing import List, Optional, Callable, Set

from PyQt6.QtCore import QTimer

from utils.win32_helpers import (
    get_visible_windows, get_foreground_window, move_window,
    get_taskbar_rect, WindowInfo,
    register_window_event_hook, unregister_all_hooks,
    EVENT_OBJECT_CREATE, EVENT_OBJECT_DESTROY, EVENT_OBJECT_SHOW,
)


_JUNK_PATTERNS = (
    "mainwindowview", "applicationframehost",
    "softwareupdatenotification", "progman", "workerw",
)


def _is_junk_window(title: str, process_name: str) -> bool:
    """Return True if a window looks like system noise rather than a real user window."""
    t = title.lower()
    p = process_name.lower()
    # Bare executable name as title
    if t.endswith(".exe"):
        return True
    # Internal/system window names
    if t.startswith("_"):
        return True
    # Our own pet process
    if p in ("python.exe", "pythonw.exe") or t == "python":
        return True
    # Known system junk patterns
    if any(pat in t for pat in _JUNK_PATTERNS):
        return True
    # Very short generic title (likely internal)
    if len(t) < 3:
        return True
    return False


class WindowAwareness:
    """
    Monitors desktop windows and triggers pet behaviors:
    - Detect nearby windows for platform walking
    - Read window titles and comment on them
    - Push/nudge windows
    - Peek from behind window edges
    - React to window open/close events
    """

    def __init__(self, pet_window):
        self._pet_window = pet_window
        self._known_hwnds: Set[int] = set()
        self._windows: List[WindowInfo] = []
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_windows)
        self._enabled = True
        self._push_enabled = True

        # Callbacks
        self._on_window_opened: Optional[Callable[[WindowInfo], None]] = None
        self._on_window_closed: Optional[Callable[[WindowInfo], None]] = None

    @property
    def windows(self) -> List[WindowInfo]:
        return self._windows

    def start(self, poll_interval_ms: int = 3000):
        """Start monitoring windows."""
        self._poll_windows()  # initial poll
        self._poll_timer.start(poll_interval_ms)
        try:
            register_window_event_hook(self._on_win_event)
        except Exception:
            pass  # hooks are optional; polling is the fallback

    def stop(self):
        """Stop monitoring."""
        self._poll_timer.stop()
        try:
            unregister_all_hooks()
        except Exception:
            pass

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    def set_push_enabled(self, enabled: bool):
        self._push_enabled = enabled

    def set_callbacks(self,
                      on_opened: Optional[Callable[[WindowInfo], None]] = None,
                      on_closed: Optional[Callable[[WindowInfo], None]] = None):
        self._on_window_opened = on_opened
        self._on_window_closed = on_closed

    def _poll_windows(self):
        """Poll current windows and detect changes."""
        if not self._enabled:
            return
        try:
            new_windows = get_visible_windows()
        except Exception:
            return

        new_hwnds = {w.hwnd for w in new_windows}
        old_hwnds = self._known_hwnds

        # Detect newly opened windows
        opened = new_hwnds - old_hwnds
        for w in new_windows:
            if w.hwnd in opened and self._on_window_opened:
                if not _is_junk_window(w.title, w.process_name):
                    self._on_window_opened(w)

        # Detect closed windows
        closed = old_hwnds - new_hwnds
        if self._on_window_closed:
            for hwnd in closed:
                # Find the stored WindowInfo for this handle
                for ow in self._windows:
                    if ow.hwnd == hwnd:
                        if not _is_junk_window(ow.title, ow.process_name):
                            self._on_window_closed(ow)
                        break

        self._windows = new_windows
        self._known_hwnds = new_hwnds

        # Update movement engine platforms
        self._pet_window.movement.update_platforms(new_windows)

    def _on_win_event(self, event_type: int, hwnd: int):
        """Callback from win32 event hook (runs on hook thread)."""
        # We rely on polling for accuracy; this is just for responsiveness
        pass

    def get_interesting_windows(self) -> List[WindowInfo]:
        """Return windows filtered to only user-facing, meaningful ones."""
        return [w for w in self._windows if not _is_junk_window(w.title, w.process_name)]

    def get_nearby_windows(self, pet_x: int, pet_y: int, radius: int = 200) -> List[WindowInfo]:
        """Get windows whose edges are near the pet's position."""
        nearby = []
        for w in self._windows:
            # Check if pet is near any edge of this window
            dist_left = abs(pet_x - w.left)
            dist_right = abs(pet_x - w.right)
            dist_top = abs(pet_y - w.top)
            if min(dist_left, dist_right) < radius or dist_top < radius:
                nearby.append(w)
        return nearby

    def try_push_window(self, pet_x: int, pet_y: int) -> Optional[WindowInfo]:
        """
        Try to push a nearby non-maximized window.
        Returns the pushed window or None.
        """
        if not self._push_enabled or not self._enabled:
            return None

        nearby = self.get_nearby_windows(pet_x, pet_y, radius=100)
        candidates = [w for w in nearby if not w.is_maximized and not w.is_minimized]
        if not candidates:
            return None

        target = random.choice(candidates)
        # Nudge 20-50px in the direction the pet is facing
        direction = self._pet_window.pet.direction
        dx = random.randint(20, 50) * direction
        success = move_window(target.hwnd, dx, 0)
        return target if success else None

    def get_peek_position(self, pet_size: int) -> Optional[dict]:
        """
        Find a window edge where Jacky can peek from.
        Returns dict with x, y, side ('left' or 'right') or None.
        """
        if not self._enabled or not self._windows:
            return None

        candidates = [w for w in self._windows if not w.is_minimized and w.width > pet_size * 2]
        if not candidates:
            return None

        w = random.choice(candidates)
        side = random.choice(["left", "right"])
        if side == "left":
            x = w.left - pet_size // 2  # half hidden behind left edge
            y = w.top
        else:
            x = w.right - pet_size // 2  # half hidden behind right edge
            y = w.top
        return {"x": x, "y": y, "side": side, "window": w}

    def get_window_comment_context(self) -> str:
        """Build a context string describing visible windows, for LLM prompts."""
        if not self._windows:
            return "No windows are open."
        titles = [w.title for w in self._windows[:8]]  # limit to 8
        return "Open windows: " + ", ".join(titles)
