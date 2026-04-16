# -*- coding: utf-8 -*-
"""Platform Abstraction Layer — macOS backend.

Uses pyobjc (Cocoa, Quartz, ApplicationServices) for native macOS integration.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from pal.base import PlatformBackend, WindowInfo

log = logging.getLogger("pal.macos")

# ── Lazy imports (only on macOS) ─────────────────────────────────────────────

try:
    import Cocoa
    import Quartz
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
        kCGWindowLayer,
        kCGWindowOwnerPID,
        kCGWindowOwnerName,
        kCGWindowName,
        kCGWindowBounds,
        kCGWindowNumber,
        CGEventCreateMouseEvent,
        CGEventCreateKeyboardEvent,
        CGEventPost,
        CGEventSetFlags,
        CGEventSourceCreate,
        CGEventSourceSecondsSinceLastEventType,
        kCGEventSourceStateHIDSystemState,
        kCGEventSourceStateCombinedSessionState,
        kCGAnyInputEventType,
        kCGHIDEventTap,
        kCGEventMouseMoved,
        kCGEventLeftMouseDown,
        kCGEventLeftMouseUp,
        kCGMouseButtonLeft,
        kCGEventFlagMaskCommand,
        kCGEventFlagMaskShift,
        kCGEventFlagMaskAlternate,
        kCGEventFlagMaskControl,
        CGEventKeyboardSetUnicodeString,
        CGPoint,
    )
    from ApplicationServices import (
        AXUIElementCreateApplication,
        AXUIElementCopyAttributeValue,
        AXUIElementSetAttributeValue,
        AXUIElementPerformAction,
        AXIsProcessTrusted,
        AXIsProcessTrustedWithOptions,
        kAXTrustedCheckOptionPrompt,
        kAXWindowsAttribute,
        kAXPositionAttribute,
        kAXSizeAttribute,
        kAXMinimizedAttribute,
        kAXFocusedAttribute,
        kAXRaiseAction,
        kAXErrorSuccess,
    )
    _HAS_PYOBJC = True
except ImportError:
    _HAS_PYOBJC = False

_OWN_PID = os.getpid()

# ── Accessibility helper ─────────────────────────────────────────────────────


def _check_accessibility(prompt: bool = False) -> bool:
    """Return True if this process has Accessibility permission."""
    if not _HAS_PYOBJC:
        return False
    if prompt:
        opts = {kAXTrustedCheckOptionPrompt: True}
        return AXIsProcessTrustedWithOptions(opts)
    return AXIsProcessTrusted()


# ── AX helpers ───────────────────────────────────────────────────────────────


def _ax_windows_for_pid(pid: int):
    """Return list of AXUIElement windows for a PID, or empty list."""
    app = AXUIElementCreateApplication(pid)
    err, windows = AXUIElementCopyAttributeValue(app, kAXWindowsAttribute, None)
    if err == kAXErrorSuccess and windows:
        return list(windows)
    return []


def _ax_get_pos_size(win_el):
    """Return ((x, y), (w, h)) for an AX window element, or None."""
    err, pos_val = AXUIElementCopyAttributeValue(win_el, kAXPositionAttribute, None)
    if err != kAXErrorSuccess:
        return None
    err, size_val = AXUIElementCopyAttributeValue(win_el, kAXSizeAttribute, None)
    if err != kAXErrorSuccess:
        return None
    pos = Cocoa.NSPoint()
    size = Cocoa.NSSize()
    if not Quartz.AXValueGetValue(pos_val, Quartz.kAXValueCGPointType, pos):
        return None
    if not Quartz.AXValueGetValue(size_val, Quartz.kAXValueCGSizeType, size):
        return None
    return (pos.x, pos.y), (size.width, size.height)


def _ax_set_position(win_el, x: float, y: float) -> bool:
    pt = CGPoint(x, y)
    val = Quartz.AXValueCreate(Quartz.kAXValueCGPointType, pt)
    return AXUIElementSetAttributeValue(win_el, kAXPositionAttribute, val) == kAXErrorSuccess


def _ax_set_size(win_el, w: float, h: float) -> bool:
    sz = Cocoa.NSSize(w, h)
    val = Quartz.AXValueCreate(Quartz.kAXValueCGSizeType, sz)
    return AXUIElementSetAttributeValue(win_el, kAXSizeAttribute, val) == kAXErrorSuccess


def _ax_is_minimized(win_el) -> bool:
    err, val = AXUIElementCopyAttributeValue(win_el, kAXMinimizedAttribute, None)
    if err == kAXErrorSuccess:
        return bool(val)
    return False


def _find_ax_window_by_wid(pid: int, wid: int):
    """Find the AX window element matching a CGWindowNumber for a given PID."""
    for w in _ax_windows_for_pid(pid):
        ps = _ax_get_pos_size(w)
        if ps is not None:
            return w  # best effort: return first match
    return None


def _pid_for_wid(wid: int) -> Optional[int]:
    """Lookup the PID owning a CGWindowNumber."""
    info_list = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly, kCGNullWindowID
    )
    if not info_list:
        return None
    for info in info_list:
        if info.get(kCGWindowNumber, -1) == wid:
            return info.get(kCGWindowOwnerPID)
    return None


def _get_ax_window(wid: int):
    """Best-effort lookup: CGWindowNumber → PID → AX window element."""
    pid = _pid_for_wid(wid)
    if pid is None:
        return None, None
    windows = _ax_windows_for_pid(pid)
    if not windows:
        return pid, None
    # Try to match by bounds
    info_list = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly, kCGNullWindowID
    )
    target_bounds = None
    for info in (info_list or []):
        if info.get(kCGWindowNumber, -1) == wid:
            target_bounds = info.get(kCGWindowBounds)
            break
    if target_bounds and len(windows) > 1:
        tx, ty = target_bounds.get("X", 0), target_bounds.get("Y", 0)
        for w in windows:
            ps = _ax_get_pos_size(w)
            if ps and abs(ps[0][0] - tx) < 2 and abs(ps[0][1] - ty) < 2:
                return pid, w
    return pid, windows[0] if windows else None


# ── Hotkey parsing (macOS key codes) ─────────────────────────────────────────

_MAC_MOD_MAP = {
    "ctrl": kCGEventFlagMaskControl if _HAS_PYOBJC else 0,
    "control": kCGEventFlagMaskControl if _HAS_PYOBJC else 0,
    "shift": kCGEventFlagMaskShift if _HAS_PYOBJC else 0,
    "alt": kCGEventFlagMaskAlternate if _HAS_PYOBJC else 0,
    "option": kCGEventFlagMaskAlternate if _HAS_PYOBJC else 0,
    "cmd": kCGEventFlagMaskCommand if _HAS_PYOBJC else 0,
    "command": kCGEventFlagMaskCommand if _HAS_PYOBJC else 0,
    "win": kCGEventFlagMaskCommand if _HAS_PYOBJC else 0,
    "super": kCGEventFlagMaskCommand if _HAS_PYOBJC else 0,
}

# Carbon virtual key codes
_MAC_VK_MAP = {
    "space": 0x31, "enter": 0x24, "return": 0x24, "tab": 0x30,
    "escape": 0x35, "esc": 0x35, "backspace": 0x33, "delete": 0x75,
    "home": 0x73, "end": 0x77, "pageup": 0x74, "pagedown": 0x79,
    "up": 0x7E, "down": 0x7D, "left": 0x7B, "right": 0x7C,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76,
    "f5": 0x60, "f6": 0x61, "f7": 0x62, "f8": 0x64,
    "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
    # Letters (Carbon kVK_ANSI_*)
    "a": 0x00, "b": 0x0B, "c": 0x08, "d": 0x02, "e": 0x0E,
    "f": 0x03, "g": 0x05, "h": 0x04, "i": 0x22, "j": 0x26,
    "k": 0x28, "l": 0x25, "m": 0x2E, "n": 0x2D, "o": 0x1F,
    "p": 0x23, "q": 0x0C, "r": 0x0F, "s": 0x01, "t": 0x11,
    "u": 0x20, "v": 0x09, "w": 0x0D, "x": 0x07, "y": 0x10, "z": 0x06,
    # Numbers
    "0": 0x1D, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15,
    "5": 0x17, "6": 0x16, "7": 0x1A, "8": 0x1C, "9": 0x19,
}


def _parse_mac_shortcut(shortcut: str) -> Tuple[int, int]:
    """Parse shortcut string → (modifier_flags, carbon_vk).  Raises ValueError."""
    parts = [p.strip().lower() for p in shortcut.split("+")]
    if not parts:
        raise ValueError(f"Empty shortcut: {shortcut!r}")
    mods = 0
    key_part = None
    for part in parts:
        if part in _MAC_MOD_MAP:
            mods |= _MAC_MOD_MAP[part]
        else:
            if key_part is not None:
                raise ValueError(f"Multiple keys in shortcut: {shortcut!r}")
            key_part = part
    if key_part is None:
        raise ValueError(f"No key in shortcut: {shortcut!r}")
    if key_part not in _MAC_VK_MAP:
        raise ValueError(f"Unknown key {key_part!r} in shortcut: {shortcut!r}")
    return mods, _MAC_VK_MAP[key_part]


# ── Hotkey monitor handle ────────────────────────────────────────────────────


class _MacHotkeyHandle:
    """NSEvent global monitor for a single hotkey combination."""

    def __init__(self, mod_flags: int, vk: int, callback: Callable):
        self.mod_flags = mod_flags
        self.vk = vk
        self.callback = callback
        self._monitor = None

    def start(self) -> bool:
        if not _HAS_PYOBJC:
            return False
        mask = Cocoa.NSEventMaskKeyDown

        mod_flags = self.mod_flags
        vk = self.vk
        cb = self.callback

        def _handler(event):
            if event.keyCode() == vk:
                ev_mods = event.modifierFlags() & (
                    Cocoa.NSEventModifierFlagCommand
                    | Cocoa.NSEventModifierFlagShift
                    | Cocoa.NSEventModifierFlagOption
                    | Cocoa.NSEventModifierFlagControl
                )
                # Map CG flags to NS flags for comparison
                ns_mods = 0
                if mod_flags & kCGEventFlagMaskCommand:
                    ns_mods |= Cocoa.NSEventModifierFlagCommand
                if mod_flags & kCGEventFlagMaskShift:
                    ns_mods |= Cocoa.NSEventModifierFlagShift
                if mod_flags & kCGEventFlagMaskAlternate:
                    ns_mods |= Cocoa.NSEventModifierFlagOption
                if mod_flags & kCGEventFlagMaskControl:
                    ns_mods |= Cocoa.NSEventModifierFlagControl
                if ev_mods == ns_mods:
                    cb()

        self._monitor = Cocoa.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            mask, _handler
        )
        return self._monitor is not None

    def stop(self):
        if self._monitor is not None:
            Cocoa.NSEvent.removeMonitor_(self._monitor)
            self._monitor = None

    def join(self, timeout: float = 2.0):
        pass  # No thread to join — NSEvent monitor is run-loop based


# ── Notification observers ───────────────────────────────────────────────────

_observers: list = []


# ══════════════════════════════════════════════════════════════════════════════
#  MacOSBackend
# ══════════════════════════════════════════════════════════════════════════════


class MacOSBackend(PlatformBackend):
    """macOS implementation of the Platform Abstraction Layer."""

    # -- Screen / desktop geometry -----------------------------------------

    def get_screen_size(self) -> Tuple[int, int]:
        frame = Cocoa.NSScreen.mainScreen().frame()
        return (int(frame.size.width), int(frame.size.height))

    def get_work_area(self) -> Tuple[int, int, int, int]:
        screen = Cocoa.NSScreen.mainScreen()
        full = screen.frame()
        vis = screen.visibleFrame()
        # NSScreen coords are bottom-left origin; convert to top-left
        screen_h = int(full.size.height)
        left = int(vis.origin.x)
        top = screen_h - int(vis.origin.y + vis.size.height)
        right = int(vis.origin.x + vis.size.width)
        bottom = screen_h - int(vis.origin.y)
        return (left, top, right, bottom)

    def get_taskbar_rect(self) -> Tuple[int, int, int, int]:
        screen = Cocoa.NSScreen.mainScreen()
        full = screen.frame()
        vis = screen.visibleFrame()
        screen_h = int(full.size.height)
        screen_w = int(full.size.width)
        # Dock could be at bottom, left, or right.  Approximate: return the
        # largest gap between full frame and visible frame.
        gap_bottom = int(vis.origin.y - full.origin.y)
        gap_top = int((full.origin.y + full.size.height)
                      - (vis.origin.y + vis.size.height))
        gap_left = int(vis.origin.x - full.origin.x)
        gap_right = int((full.origin.x + full.size.width)
                        - (vis.origin.x + vis.size.width))

        # Menu bar is always the top gap on macOS
        # Return the Dock region (largest non-menu-bar gap), or bottom fallback
        if gap_bottom >= max(gap_left, gap_right):
            return (0, screen_h - gap_bottom, screen_w, screen_h)
        elif gap_left >= gap_right:
            return (0, 0, gap_left, screen_h)
        else:
            return (screen_w - gap_right, 0, screen_w, screen_h)

    # -- Window enumeration ------------------------------------------------

    def get_visible_windows(self, exclude_pids: Optional[set] = None) -> List[WindowInfo]:
        windows: List[WindowInfo] = []
        _exclude = exclude_pids or set()
        info_list = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID
        )
        if not info_list:
            return windows
        screen_h = self.get_screen_size()[1]
        for info in info_list:
            layer = info.get(kCGWindowLayer, -1)
            if layer != 0:
                continue
            pid = info.get(kCGWindowOwnerPID, 0)
            if pid == _OWN_PID or pid in _exclude:
                continue
            title = info.get(kCGWindowName, "") or info.get(kCGWindowOwnerName, "")
            if not title:
                continue
            bounds = info.get(kCGWindowBounds)
            if not bounds:
                continue
            # CG bounds are top-left origin already
            x = int(bounds.get("X", 0))
            y = int(bounds.get("Y", 0))
            w = int(bounds.get("Width", 0))
            h = int(bounds.get("Height", 0))
            if w < 1 or h < 1:
                continue
            wid = info.get(kCGWindowNumber, 0)
            pname = info.get(kCGWindowOwnerName, "")
            windows.append(WindowInfo(
                hwnd=wid, title=title,
                rect=(x, y, x + w, y + h),
                is_maximized=False,  # macOS doesn't have true "maximized" state
                is_minimized=False,
                process_name=pname,
            ))
        return windows

    def get_foreground_window(self) -> Optional[WindowInfo]:
        ws = Cocoa.NSWorkspace.sharedWorkspace()
        front_app = ws.frontmostApplication()
        if not front_app:
            return None
        front_pid = front_app.processIdentifier()
        info_list = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID
        )
        if not info_list:
            return None
        for info in info_list:
            if info.get(kCGWindowOwnerPID) != front_pid:
                continue
            if info.get(kCGWindowLayer, -1) != 0:
                continue
            bounds = info.get(kCGWindowBounds)
            if not bounds:
                continue
            x = int(bounds.get("X", 0))
            y = int(bounds.get("Y", 0))
            w = int(bounds.get("Width", 0))
            h = int(bounds.get("Height", 0))
            wid = info.get(kCGWindowNumber, 0)
            title = info.get(kCGWindowName, "") or info.get(kCGWindowOwnerName, "")
            return WindowInfo(
                hwnd=wid, title=title,
                rect=(x, y, x + w, y + h),
                is_maximized=False, is_minimized=False,
                process_name=info.get(kCGWindowOwnerName, ""),
            )
        return None

    # -- Window manipulation -----------------------------------------------

    def move_window(self, wid: int, dx: int, dy: int) -> bool:
        if not _check_accessibility():
            return False
        pid, ax_win = _get_ax_window(wid)
        if ax_win is None:
            return False
        ps = _ax_get_pos_size(ax_win)
        if ps is None:
            return False
        (cx, cy), _ = ps
        return _ax_set_position(ax_win, cx + dx, cy + dy)

    def set_window_pos(self, wid: int, x: int, y: int) -> bool:
        if not _check_accessibility():
            return False
        _, ax_win = _get_ax_window(wid)
        if ax_win is None:
            return False
        return _ax_set_position(ax_win, x, y)

    def resize_window(self, wid: int, dw: int, dh: int) -> bool:
        if not _check_accessibility():
            return False
        _, ax_win = _get_ax_window(wid)
        if ax_win is None:
            return False
        ps = _ax_get_pos_size(ax_win)
        if ps is None:
            return False
        _, (cw, ch) = ps
        new_w = max(200, cw + dw)
        new_h = max(150, ch + dh)
        return _ax_set_size(ax_win, new_w, new_h)

    def minimize_window(self, wid: int) -> bool:
        if not _check_accessibility():
            return False
        _, ax_win = _get_ax_window(wid)
        if ax_win is None:
            return False
        err = AXUIElementSetAttributeValue(ax_win, kAXMinimizedAttribute, True)
        return err == kAXErrorSuccess

    def flash_window(self, wid: int, count: int = 3) -> bool:
        try:
            Cocoa.NSApplication.sharedApplication().requestUserAttention_(
                Cocoa.NSInformationalRequest
            )
            return True
        except Exception:
            return False

    def set_foreground_window(self, wid: int) -> bool:
        if not _check_accessibility():
            return False
        pid, ax_win = _get_ax_window(wid)
        if ax_win is None:
            return False
        AXUIElementPerformAction(ax_win, kAXRaiseAction)
        # Also activate the owning app
        if pid:
            app = Cocoa.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
            if app:
                app.activateWithOptions_(Cocoa.NSApplicationActivateIgnoringOtherApps)
        return True

    def tile_windows(self, wids: List[int]) -> bool:
        if not wids or not _check_accessibility():
            return False
        try:
            wa_l, wa_t, wa_r, wa_b = self.get_work_area()
            wa_w = wa_r - wa_l
            wa_h = wa_b - wa_t
            n = len(wids)
            cols = max(1, int(n ** 0.5))
            rows = (n + cols - 1) // cols
            cell_w = wa_w // cols
            cell_h = wa_h // rows
            for i, wid in enumerate(wids):
                col = i % cols
                row = i // cols
                x = wa_l + col * cell_w
                y = wa_t + row * cell_h
                _, ax_win = _get_ax_window(wid)
                if ax_win:
                    _ax_set_position(ax_win, x, y)
                    _ax_set_size(ax_win, cell_w, cell_h)
            return True
        except Exception:
            return False

    def get_window_rect(self, wid: int) -> Optional[Tuple[int, int, int, int]]:
        info_list = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID
        )
        if not info_list:
            return None
        for info in info_list:
            if info.get(kCGWindowNumber, -1) == wid:
                bounds = info.get(kCGWindowBounds)
                if bounds:
                    x = int(bounds.get("X", 0))
                    y = int(bounds.get("Y", 0))
                    w = int(bounds.get("Width", 0))
                    h = int(bounds.get("Height", 0))
                    return (x, y, x + w, y + h)
        return None

    # -- Pet-window chrome -------------------------------------------------

    def _get_nswindow(self, view_ptr: int):
        """Convert a Qt winId() NSView* pointer to the owning NSWindow.

        Qt's ``winId()`` on macOS returns the address of the ``NSView`` that
        backs the QWidget.  We use pyobjc to wrap that raw pointer and call
        ``-[NSView window]`` to retrieve the parent ``NSWindow``.
        Returns ``None`` on any failure.
        """
        try:
            import objc
            import ctypes
            # pyobjc accepts either a plain int or ctypes.c_void_p for c_void_p=
            try:
                nsview = objc.objc_object(c_void_p=ctypes.c_void_p(view_ptr))
            except TypeError:
                nsview = objc.objc_object(c_void_p=view_ptr)
            win = nsview.window() if hasattr(nsview, 'window') else None
            if win is None:
                log.debug("_get_nswindow: NSView.window() returned nil for ptr=%s", view_ptr)
            return win
        except Exception as exc:
            log.debug("_get_nswindow failed: %s", exc)
            return None

    def set_topmost(self, wid: int) -> None:
        """Set window to floating level and ensure it never hides on deactivation.

        On macOS, Qt's winId() returns an NSView* pointer (not a CGWindowID /
        windowNumber). We cast it via objc to get the owning NSWindow/NSPanel.

        Key issues this fixes:
        - Qt.WindowType.Tool creates an NSPanel with hidesOnDeactivate=YES by
          default. This causes the window to sink behind others whenever a
          different app is focused. We disable that.
        - NSFloatingWindowLevel keeps it above normal (level 0) app windows.
        - NSWindowCollectionBehaviorCanJoinAllSpaces keeps it visible across
          Mission Control spaces without stealing focus.
        """
        try:
            nswin = self._get_nswindow(wid)
            if nswin is None:
                log.debug("set_topmost: _get_nswindow returned None for wid=%s", wid)
                return
            # NSFloatingWindowLevel (3) sits above normal app windows (0).
            nswin.setLevel_(Cocoa.NSFloatingWindowLevel)
            # CRITICAL: NSPanel created by Qt.Tool has hidesOnDeactivate=YES,
            # which hides the window when another app is focused. Disable it.
            if hasattr(nswin, 'setHidesOnDeactivate_'):
                nswin.setHidesOnDeactivate_(False)
            # Visible on all Spaces without stealing focus.
            nswin.setCollectionBehavior_(
                Cocoa.NSWindowCollectionBehaviorCanJoinAllSpaces
            )
            log.debug("set_topmost: NSFloatingWindowLevel applied wid=%s", wid)
        except Exception as exc:
            log.debug("set_topmost failed: %s", exc)


    def remove_window_border(self, wid: int) -> None:
        try:
            nswin = self._get_nswindow(wid)
            if nswin is not None:
                nswin.setHasShadow_(False)
        except Exception:
            pass

    def set_click_through(self, wid: int, enabled: bool) -> bool:
        try:
            nswin = self._get_nswindow(wid)
            if nswin is not None:
                nswin.setIgnoresMouseEvents_(enabled)
                return True
        except Exception:
            pass
        return False

    # -- Cursor / input simulation -----------------------------------------

    def get_cursor_position(self) -> Tuple[int, int]:
        loc = Cocoa.NSEvent.mouseLocation()
        screen_h = self.get_screen_size()[1]
        # NSEvent coords are bottom-left; convert to top-left
        return (int(loc.x), int(screen_h - loc.y))

    def set_cursor_position(self, x: int, y: int) -> bool:
        try:
            pt = CGPoint(x, y)
            src = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
            evt = CGEventCreateMouseEvent(src, kCGEventMouseMoved, pt, kCGMouseButtonLeft)
            CGEventPost(kCGHIDEventTap, evt)
            return True
        except Exception:
            return False

    def click_at(self, x: int, y: int, safety_check: bool = True) -> bool:
        if not self.set_cursor_position(x, y):
            return False
        if safety_check:
            time.sleep(0.05)
            cx, cy = self.get_cursor_position()
            if abs(cx - x) > 20 or abs(cy - y) > 20:
                return False
        try:
            pt = CGPoint(x, y)
            src = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
            down = CGEventCreateMouseEvent(src, kCGEventLeftMouseDown, pt, kCGMouseButtonLeft)
            CGEventPost(kCGHIDEventTap, down)
            time.sleep(0.05)
            up = CGEventCreateMouseEvent(src, kCGEventLeftMouseUp, pt, kCGMouseButtonLeft)
            CGEventPost(kCGHIDEventTap, up)
            return True
        except Exception:
            return False

    def send_close_window(self) -> bool:
        """Send Cmd+W to close the foreground window."""
        try:
            src = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
            vk_w = 0x0D  # kVK_ANSI_W
            down = CGEventCreateKeyboardEvent(src, vk_w, True)
            CGEventSetFlags(down, kCGEventFlagMaskCommand)
            up = CGEventCreateKeyboardEvent(src, vk_w, False)
            CGEventSetFlags(up, kCGEventFlagMaskCommand)
            CGEventPost(kCGHIDEventTap, down)
            time.sleep(0.05)
            CGEventPost(kCGHIDEventTap, up)
            return True
        except Exception:
            return False

    def minimize_foreground_window(self) -> bool:
        """Send Cmd+M to minimize the foreground window."""
        try:
            src = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
            vk_m = 0x2E  # kVK_ANSI_M
            down = CGEventCreateKeyboardEvent(src, vk_m, True)
            CGEventSetFlags(down, kCGEventFlagMaskCommand)
            up = CGEventCreateKeyboardEvent(src, vk_m, False)
            CGEventSetFlags(up, kCGEventFlagMaskCommand)
            CGEventPost(kCGHIDEventTap, down)
            time.sleep(0.05)
            CGEventPost(kCGHIDEventTap, up)
            return True
        except Exception:
            return False

    def type_text(self, text: str, char_delay: float = 0.02) -> bool:
        if not text:
            return False
        try:
            src = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
            for char in text:
                down = CGEventCreateKeyboardEvent(src, 0, True)
                CGEventKeyboardSetUnicodeString(down, len(char), char)
                up = CGEventCreateKeyboardEvent(src, 0, False)
                CGEventKeyboardSetUnicodeString(up, len(char), char)
                CGEventPost(kCGHIDEventTap, down)
                CGEventPost(kCGHIDEventTap, up)
                if char_delay > 0:
                    time.sleep(char_delay)
            return True
        except Exception:
            return False

    # -- System information ------------------------------------------------

    def get_power_status(self) -> Tuple[bool, int]:
        try:
            import subprocess
            out = subprocess.check_output(
                ["pmset", "-g", "batt"], text=True, timeout=2
            )
            ac = "AC Power" in out
            pct = -1
            for line in out.splitlines():
                if "%" in line:
                    import re
                    m = re.search(r"(\d+)%", line)
                    if m:
                        pct = int(m.group(1))
                    break
            return (ac, pct)
        except Exception:
            return (True, -1)

    def get_idle_seconds(self) -> float:
        try:
            return CGEventSourceSecondsSinceLastEventType(
                kCGEventSourceStateCombinedSessionState,
                kCGAnyInputEventType,
            )
        except Exception:
            return 0.0

    # -- Global hotkey -----------------------------------------------------

    def validate_shortcut(self, shortcut: str) -> None:
        _parse_mac_shortcut(shortcut)

    def register_hotkey(self, shortcut: str, key_id: int,
                        callback: Callable) -> Optional[_MacHotkeyHandle]:
        try:
            mods, vk = _parse_mac_shortcut(shortcut)
        except ValueError as exc:
            log.error("Invalid shortcut: %s", exc)
            return None
        handle = _MacHotkeyHandle(mods, vk, callback)
        if handle.start():
            log.info("Registered global hotkey: %s", shortcut)
            return handle
        log.error("Failed to register global hotkey: %s", shortcut)
        return None

    def unregister_hotkey(self, handle) -> None:
        if handle is not None:
            handle.stop()

    # -- Window-event hooks ------------------------------------------------

    def register_window_event_hook(self, callback: Callable) -> None:
        nc = Cocoa.NSWorkspace.sharedWorkspace().notificationCenter()

        def _on_launch(notif):
            callback(0x8000, 0)  # EVENT_OBJECT_CREATE

        def _on_terminate(notif):
            callback(0x8001, 0)  # EVENT_OBJECT_DESTROY

        def _on_activate(notif):
            callback(0x8002, 0)  # EVENT_OBJECT_SHOW

        names = [
            ("NSWorkspaceDidLaunchApplicationNotification", _on_launch),
            ("NSWorkspaceDidTerminateApplicationNotification", _on_terminate),
            ("NSWorkspaceDidActivateApplicationNotification", _on_activate),
        ]
        for name, handler in names:
            nc.addObserverForName_object_queue_usingBlock_(
                name, None, None, handler,
            )
            _observers.append((nc, name, handler))

    def unregister_all_hooks(self) -> None:
        for nc, name, handler in _observers:
            try:
                nc.removeObserver_name_object_(handler, name, None)
            except Exception:
                pass
        _observers.clear()
