import random
from typing import List, Optional, Callable, Set

from PyQt6.QtCore import QTimer

from pal import (
    backend,
    get_visible_windows, get_foreground_window, move_window,
    set_window_pos, resize_window, minimize_window,
    flash_window, set_foreground_window, tile_windows,
    get_taskbar_rect, WindowInfo,
    register_window_event_hook, unregister_all_hooks,
    EVENT_OBJECT_CREATE, EVENT_OBJECT_DESTROY, EVENT_OBJECT_SHOW,
)


_JUNK_PATTERNS = (
    "mainwindowview", "applicationframehost",
    "softwareupdatenotification", "progman", "workerw",
)

# Executables whose windows are always junk regardless of title
_JUNK_PROCESSES = (
    "applicationframehost.exe",
    "python.exe",
    "pythonw.exe",
    "python3.exe",
    "conhost.exe",
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
    # Known system junk patterns — check both title and process name
    if any(pat in t or pat in p for pat in _JUNK_PATTERNS):
        return True
    # Executables that are always junk
    if any(p == proc for proc in _JUNK_PROCESSES):
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
        self._peer_pids: Set[int] = set()

        # Callbacks
        self._on_window_opened: Optional[Callable[[WindowInfo], None]] = None
        self._on_window_closed: Optional[Callable[[WindowInfo], None]] = None

    @property
    def windows(self) -> List[WindowInfo]:
        return self._windows

    def start(self, poll_interval_ms: int = 3000):
        """Start monitoring windows."""
        # Seed known windows without firing open/close callbacks so existing
        # windows at launch don't each trigger an LLM request.
        try:
            initial = get_visible_windows()
        except Exception:
            initial = []
        self._windows = initial
        self._known_hwnds = {w.hwnd for w in initial}
        self._pet_window.movement.update_platforms(initial)

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

    def set_peer_pids(self, pids: Set[int]):
        """Set PIDs of peer Jacky processes (all their windows are excluded)."""
        self._peer_pids = pids

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
            new_windows = get_visible_windows(exclude_pids=self._peer_pids)
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
            if _is_junk_window(w.title, w.process_name):
                continue
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

        candidates = [w for w in self._windows
                      if not w.is_minimized and w.width > pet_size * 2
                      and not _is_junk_window(w.title, w.process_name)]
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

    def try_shake_window(self, pet_x: int, pet_y: int) -> Optional[WindowInfo]:
        """
        Shake a nearby window back and forth rapidly.
        Returns the shaken window or None.
        """
        if not self._push_enabled or not self._enabled:
            return None

        nearby = self.get_nearby_windows(pet_x, pet_y, radius=150)
        candidates = [w for w in nearby if not w.is_maximized and not w.is_minimized]
        if not candidates:
            return None

        target = random.choice(candidates)
        return target

    def do_shake_step(self, hwnd: int, step: int) -> bool:
        """Perform one step of the shake animation. Returns False when done."""
        offsets = [8, -16, 16, -16, 12, -8, 4, 0]
        if step >= len(offsets):
            return False
        move_window(hwnd, offsets[step], 0)
        return True

    def try_minimize_window(self, pet_x: int, pet_y: int) -> Optional[WindowInfo]:
        """
        Minimize a nearby non-maximized window.
        Returns the minimized window or None.
        """
        if not self._push_enabled or not self._enabled:
            return None

        nearby = self.get_nearby_windows(pet_x, pet_y, radius=150)
        candidates = [w for w in nearby if not w.is_maximized and not w.is_minimized]
        if not candidates:
            return None

        target = random.choice(candidates)
        success = minimize_window(target.hwnd)
        return target if success else None

    def get_titlebar_position(self, pet_size: int) -> Optional[dict]:
        """
        Find a window title bar for the pet to sit on.
        Returns dict with x, y, window or None.
        """
        if not self._enabled or not self._windows:
            return None

        candidates = [w for w in self._windows
                      if not w.is_minimized and not w.is_maximized
                      and w.width > pet_size
                      and w.top >= pet_size
                      and not _is_junk_window(w.title, w.process_name)]
        if not candidates:
            return None

        w = random.choice(candidates)
        x = w.left + random.randint(pet_size // 2, max(pet_size // 2, w.width - pet_size))
        y = w.top - pet_size  # sit on top of the title bar
        return {"x": x, "y": y, "window": w}

    def try_resize_window(self, pet_x: int, pet_y: int) -> Optional[WindowInfo]:
        """
        Resize a nearby non-maximized window (shrink or grow randomly).
        Returns the resized window or None.
        """
        if not self._push_enabled or not self._enabled:
            return None

        nearby = self.get_nearby_windows(pet_x, pet_y, radius=150)
        candidates = [w for w in nearby if not w.is_maximized and not w.is_minimized]
        if not candidates:
            return None

        target = random.choice(candidates)
        action = random.choice(["shrink", "grow"])
        if action == "shrink":
            dw = random.randint(-100, -30)
            dh = random.randint(-80, -20)
        else:
            dw = random.randint(30, 100)
            dh = random.randint(20, 80)
        success = resize_window(target.hwnd, dw, dh)
        return target if success else None

    def try_knock_window(self) -> Optional[WindowInfo]:
        """
        Knock on a background window to bring it to attention.
        Returns the knocked window or None.
        """
        if not self._push_enabled or not self._enabled or not self._windows:
            return None

        # Pick a non-foreground window
        fg = get_foreground_window()
        candidates = [w for w in self._windows
                      if not w.is_minimized
                      and (fg is None or w.hwnd != fg.hwnd)
                      and not _is_junk_window(w.title, w.process_name)]
        if not candidates:
            return None

        target = random.choice(candidates)
        flash_window(target.hwnd, count=3)
        set_foreground_window(target.hwnd)
        return target

    def start_drag_window(self, pet_x: int, pet_y: int) -> Optional[WindowInfo]:
        """
        Pick a nearby window to drag along with the pet.
        Returns the target window or None.
        """
        if not self._push_enabled or not self._enabled:
            return None

        nearby = self.get_nearby_windows(pet_x, pet_y, radius=100)
        candidates = [w for w in nearby if not w.is_maximized and not w.is_minimized]
        if not candidates:
            return None

        return random.choice(candidates)

    def drag_window_tick(self, hwnd: int, pet_x: int, pet_y: int, pet_size: int):
        """Move the dragged window so its top-center follows the pet."""
        try:
            rect = backend.get_window_rect(hwnd)
            w_width = rect[2] - rect[0]
            target_x = pet_x + pet_size // 2 - w_width // 2
            target_y = pet_y + pet_size  # window hangs below the pet
            set_window_pos(hwnd, target_x, target_y)
        except Exception:
            pass

    def try_tidy_windows(self) -> bool:
        """
        Tile all non-maximized, non-minimized windows into a neat grid.
        Returns True if windows were tidied.
        """
        if not self._push_enabled or not self._enabled:
            return False

        candidates = [w for w in self._windows
                      if not w.is_maximized and not w.is_minimized
                      and not _is_junk_window(w.title, w.process_name)]
        if len(candidates) < 2:
            return False

        hwnds = [w.hwnd for w in candidates]
        return tile_windows(hwnds)

    def try_topple_windows(self, pet_x: int, pet_y: int, direction: int) -> List[WindowInfo]:
        """
        Chain-push windows like dominoes in the pet's facing direction.
        Returns the list of toppled windows.
        """
        if not self._push_enabled or not self._enabled:
            return []

        candidates = [w for w in self._windows
                      if not w.is_maximized and not w.is_minimized
                      and not _is_junk_window(w.title, w.process_name)]
        if not candidates:
            return []

        # Sort by horizontal position in the push direction
        if direction > 0:
            candidates.sort(key=lambda w: w.left)
        else:
            candidates.sort(key=lambda w: -w.right)

        # Push each window, increasing the offset
        toppled = []
        dx_base = 30 * direction
        for i, w in enumerate(candidates[:5]):  # max 5 windows
            dx = dx_base * (i + 1)
            if move_window(w.hwnd, dx, 0):
                toppled.append(w)
        return toppled

    def get_window_comment_context(self) -> str:
        """Build a context string describing visible windows, for LLM prompts."""
        if not self._windows:
            return "No windows are open."
        titles = [w.title for w in self._windows[:8]]  # limit to 8
        return "Open windows: " + ", ".join(titles)
