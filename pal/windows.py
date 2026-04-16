# -*- coding: utf-8 -*-
"""Platform Abstraction Layer — Windows backend.

Consolidates all Win32-specific code from the former ``utils/win32_helpers.py``,
``utils/dwm_helpers.py``, power-status helpers from ``core/system_events.py``,
and global-hotkey machinery from ``interaction/hotkey.py``.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import os
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

import win32api
import win32con
import win32gui
import win32process

from pal.base import PlatformBackend, WindowInfo

log = logging.getLogger("pal.windows")

# ── Module-level helpers & state ─────────────────────────────────────────────

_OWN_PID = os.getpid()

_process_name_cache: Dict[int, Tuple[str, float]] = {}
_PROCESS_CACHE_TTL = 30.0  # seconds


def _get_process_name(hwnd: int) -> str:
    """Get the process name for a window handle (cached by PID, TTL 30s)."""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except Exception:
        return ""

    now = time.monotonic()
    cached = _process_name_cache.get(pid)
    if cached is not None and (now - cached[1]) < _PROCESS_CACHE_TTL:
        return cached[0]

    try:
        handle = win32api.OpenProcess(0x0410, False, pid)  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
        exe = win32process.GetModuleFileNameEx(handle, 0)
        win32api.CloseHandle(handle)
        name = exe.split("\\")[-1] if exe else ""
    except Exception:
        name = ""

    _process_name_cache[pid] = (name, now)
    return name


# ── Cursor / input constants ─────────────────────────────────────────────────

_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_CURSOR_SAFETY_THRESHOLD = 20  # pixels


# ── Keyboard input structures ────────────────────────────────────────────────

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", _KEYBDINPUT),
        ("mi", _MOUSEINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _INPUT_UNION),
    ]


_INPUT_KEYBOARD = 1
_KEYEVENTF_UNICODE = 0x0004
_KEYEVENTF_KEYUP = 0x0002


# ── WinEvent hook machinery ─────────────────────────────────────────────────

_user32 = ctypes.windll.user32

WinEventProcType = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,   # hWinEventHook
    wintypes.DWORD,    # event
    wintypes.HWND,     # hwnd
    ctypes.c_long,     # idObject
    ctypes.c_long,     # idChild
    wintypes.DWORD,    # idEventThread
    wintypes.DWORD,    # dwmsEventTime
)

EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW = 0x8002
WINEVENT_OUTOFCONTEXT = 0x0000

_active_hooks: list = []
_active_callbacks: list = []  # prevent GC


# ── Power / idle Win32 structures ────────────────────────────────────────────

class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_byte),
        ("BatteryFlag", ctypes.c_byte),
        ("BatteryLifePercent", ctypes.c_byte),
        ("SystemStatusFlag", ctypes.c_byte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_ulong),
    ]


# ── Hotkey parsing ───────────────────────────────────────────────────────────

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

_MOD_MAP = {
    "ctrl":    MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift":   MOD_SHIFT,
    "alt":     MOD_ALT,
    "win":     MOD_WIN,
    "super":   MOD_WIN,
}

_VK_MAP = {
    "space":      0x20,
    "enter":      0x0D,
    "return":     0x0D,
    "tab":        0x09,
    "escape":     0x1B,
    "esc":        0x1B,
    "backspace":  0x08,
    "delete":     0x2E,
    "insert":     0x2D,
    "home":       0x24,
    "end":        0x23,
    "pageup":     0x21,
    "pagedown":   0x22,
    "up":         0x26,
    "down":       0x28,
    "left":       0x25,
    "right":      0x27,
    "f1":  0x70, "f2":  0x71, "f3":  0x72, "f4":  0x73,
    "f5":  0x74, "f6":  0x75, "f7":  0x76, "f8":  0x77,
    "f9":  0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}

for _c in range(ord('a'), ord('z') + 1):
    _VK_MAP[chr(_c)] = _c - 32
for _c in range(0, 10):
    _VK_MAP[str(_c)] = 0x30 + _c


def _parse_shortcut(shortcut: str) -> Tuple[int, int]:
    """Parse a shortcut string like ``'ctrl+shift+space'`` into *(modifiers, vk)*.

    Raises :class:`ValueError` if the shortcut cannot be parsed.
    """
    parts = [p.strip().lower() for p in shortcut.split("+")]
    if not parts:
        raise ValueError(f"Empty shortcut string: {shortcut!r}")

    modifiers = 0
    key_part = None

    for part in parts:
        if part in _MOD_MAP:
            modifiers |= _MOD_MAP[part]
        else:
            if key_part is not None:
                raise ValueError(
                    f"Multiple non-modifier keys in shortcut: {shortcut!r} "
                    f"(found {key_part!r} and {part!r})"
                )
            key_part = part

    if key_part is None:
        raise ValueError(f"No key found in shortcut: {shortcut!r}")

    if key_part not in _VK_MAP:
        raise ValueError(f"Unknown key {key_part!r} in shortcut: {shortcut!r}")

    return modifiers, _VK_MAP[key_part]


# ── Hotkey handle (thread + message loop) ────────────────────────────────────

class _WinHotkeyHandle:
    """Encapsulates one registered global hotkey with its own message-pump thread."""

    def __init__(self, key_id: int, modifiers: int, vk: int, callback: Callable):
        self.key_id = key_id
        self.modifiers = modifiers
        self.vk = vk
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None

    def start(self) -> bool:
        if self._running:
            return True
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def _run(self):
        if not _user32.RegisterHotKey(None, self.key_id,
                                      self.modifiers | MOD_NOREPEAT, self.vk):
            log.error("Unable to register hotkey id=%d", self.key_id)
            self._running = False
            return
        self._thread_id = threading.current_thread().native_id
        try:
            msg = wintypes.MSG()
            while self._running:
                bRet = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if bRet <= 0:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == self.key_id:
                    self.callback()
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            _user32.UnregisterHotKey(None, self.key_id)
            self._thread_id = None

    def stop(self):
        self._running = False
        tid = self._thread_id
        if self._thread and tid:
            _user32.PostThreadMessageW(tid, 0, 0, 0)

    def join(self, timeout: float = 2.0):
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)


# ══════════════════════════════════════════════════════════════════════════════
#  WindowsBackend
# ══════════════════════════════════════════════════════════════════════════════

class WindowsBackend(PlatformBackend):
    """Win32 implementation of the Platform Abstraction Layer."""

    # -- Screen / desktop geometry -----------------------------------------

    def get_screen_size(self) -> Tuple[int, int]:
        w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        return (w, h)

    def get_work_area(self) -> Tuple[int, int, int, int]:
        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
        return (rect.left, rect.top, rect.right, rect.bottom)

    def get_taskbar_rect(self) -> Tuple[int, int, int, int]:
        hwnd = win32gui.FindWindow("Shell_TrayWnd", None)
        if hwnd:
            return win32gui.GetWindowRect(hwnd)
        sw, sh = self.get_screen_size()
        return (0, sh - 48, sw, sh)

    # -- Window enumeration ------------------------------------------------

    def get_visible_windows(self, exclude_pids: Optional[set] = None) -> List[WindowInfo]:
        windows: List[WindowInfo] = []
        _exclude = exclude_pids or set()

        def _cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return True
            cls = win32gui.GetClassName(hwnd)
            if cls in {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman",
                       "WorkerW", "Windows.UI.Core.CoreWindow"}:
                return True
            try:
                rect = win32gui.GetWindowRect(hwnd)
            except Exception:
                return True
            placement = win32gui.GetWindowPlacement(hwnd)
            is_max = placement[1] == win32con.SW_SHOWMAXIMIZED
            is_min = placement[1] == win32con.SW_SHOWMINIMIZED
            if is_min:
                return True
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == _OWN_PID or pid in _exclude:
                    return True
            except Exception:
                pass
            pname = _get_process_name(hwnd)
            windows.append(WindowInfo(
                hwnd=hwnd, title=title, rect=rect,
                is_maximized=is_max, is_minimized=is_min,
                process_name=pname,
            ))
            return True

        win32gui.EnumWindows(_cb, None)
        return windows

    def get_foreground_window(self) -> Optional[WindowInfo]:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return None
        try:
            rect = win32gui.GetWindowRect(hwnd)
        except Exception:
            return None
        placement = win32gui.GetWindowPlacement(hwnd)
        is_max = placement[1] == win32con.SW_SHOWMAXIMIZED
        is_min = placement[1] == win32con.SW_SHOWMINIMIZED
        return WindowInfo(hwnd=hwnd, title=title, rect=rect,
                          is_maximized=is_max, is_minimized=is_min,
                          process_name=_get_process_name(hwnd))

    # -- Window manipulation -----------------------------------------------

    def move_window(self, wid: int, dx: int, dy: int) -> bool:
        try:
            rect = win32gui.GetWindowRect(wid)
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            win32gui.SetWindowPos(
                wid, None, rect[0] + dx, rect[1] + dy, w, h,
                win32con.SWP_NOZORDER | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
            )
            return True
        except Exception:
            return False

    def set_window_pos(self, wid: int, x: int, y: int) -> bool:
        try:
            rect = win32gui.GetWindowRect(wid)
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            win32gui.SetWindowPos(
                wid, None, x, y, w, h,
                win32con.SWP_NOZORDER | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
            )
            return True
        except Exception:
            return False

    def resize_window(self, wid: int, dw: int, dh: int) -> bool:
        try:
            rect = win32gui.GetWindowRect(wid)
            new_w = max(200, (rect[2] - rect[0]) + dw)
            new_h = max(150, (rect[3] - rect[1]) + dh)
            win32gui.SetWindowPos(
                wid, None, rect[0], rect[1], new_w, new_h,
                win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
            )
            return True
        except Exception:
            return False

    def minimize_window(self, wid: int) -> bool:
        try:
            win32gui.ShowWindow(wid, win32con.SW_MINIMIZE)
            return True
        except Exception:
            return False

    def flash_window(self, wid: int, count: int = 3) -> bool:
        try:
            class FLASHWINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint),
                    ("hwnd", ctypes.c_void_p),
                    ("dwFlags", ctypes.c_uint),
                    ("uCount", ctypes.c_uint),
                    ("dwTimeout", ctypes.c_uint),
                ]
            FLASHW_ALL = 0x00000003
            fi = FLASHWINFO()
            fi.cbSize = ctypes.sizeof(FLASHWINFO)
            fi.hwnd = wid
            fi.dwFlags = FLASHW_ALL
            fi.uCount = count
            fi.dwTimeout = 0
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(fi))
            return True
        except Exception:
            return False

    def set_foreground_window(self, wid: int) -> bool:
        try:
            win32gui.ShowWindow(wid, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(wid)
            return True
        except Exception:
            return False

    def tile_windows(self, wids: List[int]) -> bool:
        if not wids:
            return False
        try:
            wa_x, wa_y, wa_r, wa_b = self.get_work_area()
            wa_w = wa_r - wa_x
            wa_h = wa_b - wa_y
            n = len(wids)
            cols = max(1, int(n ** 0.5))
            rows = (n + cols - 1) // cols
            cell_w = wa_w // cols
            cell_h = wa_h // rows
            for i, wid in enumerate(wids):
                col = i % cols
                row = i // cols
                win32gui.SetWindowPos(
                    wid, None,
                    wa_x + col * cell_w, wa_y + row * cell_h,
                    cell_w, cell_h,
                    win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
                )
            return True
        except Exception:
            return False

    def get_window_rect(self, wid: int) -> Optional[Tuple[int, int, int, int]]:
        try:
            return win32gui.GetWindowRect(wid)
        except Exception:
            return None

    # -- Pet-window chrome -------------------------------------------------

    def set_topmost(self, wid: int) -> None:
        try:
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            _user32.SetWindowPos(
                wid, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        except Exception:
            pass

    def remove_window_border(self, wid: int) -> None:
        try:
            dwmapi = ctypes.windll.dwmapi

            # DWMWA_NCRENDERING_POLICY = 2, DWMNCRP_DISABLED = 1
            policy = ctypes.c_int(1)
            dwmapi.DwmSetWindowAttribute(wid, 2, ctypes.byref(policy), ctypes.sizeof(policy))

            # DWMWA_TRANSITIONS_FORCEDISABLED = 3
            disabled = ctypes.c_int(1)
            dwmapi.DwmSetWindowAttribute(wid, 3, ctypes.byref(disabled), ctypes.sizeof(disabled))

            # Windows 11: border colour DWMWA_COLOR_NONE
            color_none = ctypes.c_uint(0xFFFFFFFE)
            dwmapi.DwmSetWindowAttribute(wid, 34, ctypes.byref(color_none), ctypes.sizeof(color_none))

            # Windows 11: disable rounded corners
            corner = ctypes.c_int(1)
            dwmapi.DwmSetWindowAttribute(wid, 33, ctypes.byref(corner), ctypes.sizeof(corner))

            # Collapse the DWM frame to zero
            class MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", ctypes.c_int),
                    ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]
            margins = MARGINS(0, 0, 0, 0)
            dwmapi.DwmExtendFrameIntoClientArea(wid, ctypes.byref(margins))

            # Strip extended-style flags that introduce borders
            GWL_EXSTYLE = -20
            WS_EX_DLGMODALFRAME = 0x0001
            WS_EX_CLIENTEDGE = 0x0200
            WS_EX_STATICEDGE = 0x00020000
            style = _user32.GetWindowLongW(wid, GWL_EXSTYLE)
            style &= ~(WS_EX_DLGMODALFRAME | WS_EX_CLIENTEDGE | WS_EX_STATICEDGE)
            _user32.SetWindowLongW(wid, GWL_EXSTYLE, style)

            # Force frame change
            SWP_FRAMECHANGED = 0x0020
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            _user32.SetWindowPos(
                wid, 0, 0, 0, 0, 0,
                SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER,
            )
        except Exception:
            pass

    def set_click_through(self, wid: int, enabled: bool) -> bool:
        try:
            exstyle = win32gui.GetWindowLong(wid, win32con.GWL_EXSTYLE)
            if enabled:
                exstyle |= win32con.WS_EX_TRANSPARENT
            else:
                exstyle &= ~win32con.WS_EX_TRANSPARENT
            win32gui.SetWindowLong(wid, win32con.GWL_EXSTYLE, exstyle)
            return True
        except Exception:
            return False

    # -- Cursor / input simulation -----------------------------------------

    def get_cursor_position(self) -> Tuple[int, int]:
        point = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return (point.x, point.y)

    def set_cursor_position(self, x: int, y: int) -> bool:
        return bool(ctypes.windll.user32.SetCursorPos(int(x), int(y)))

    def click_at(self, x: int, y: int, safety_check: bool = True) -> bool:
        if not self.set_cursor_position(x, y):
            return False
        if safety_check:
            time.sleep(0.05)
            cx, cy = self.get_cursor_position()
            if abs(cx - x) > _CURSOR_SAFETY_THRESHOLD or abs(cy - y) > _CURSOR_SAFETY_THRESHOLD:
                return False
        ctypes.windll.user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        return True

    def send_close_window(self) -> bool:
        try:
            VK_MENU = 0x12
            VK_F4 = 0x73
            KEYEVENTF_KEYUP_C = 0x0002
            ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_F4, 0, 0, 0)
            time.sleep(0.05)
            ctypes.windll.user32.keybd_event(VK_F4, 0, KEYEVENTF_KEYUP_C, 0)
            ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP_C, 0)
            return True
        except Exception:
            return False

    def minimize_foreground_window(self) -> bool:
        try:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                return True
            return False
        except Exception:
            return False

    def type_text(self, text: str, char_delay: float = 0.02) -> bool:
        if not text:
            return False
        try:
            for char in text:
                code = ord(char)
                inputs = (_INPUT * 2)()
                inputs[0].type = _INPUT_KEYBOARD
                inputs[0].u.ki.wVk = 0
                inputs[0].u.ki.wScan = code
                inputs[0].u.ki.dwFlags = _KEYEVENTF_UNICODE
                inputs[1].type = _INPUT_KEYBOARD
                inputs[1].u.ki.wVk = 0
                inputs[1].u.ki.wScan = code
                inputs[1].u.ki.dwFlags = _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP
                ctypes.windll.user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(_INPUT))
                if char_delay > 0:
                    time.sleep(char_delay)
            return True
        except Exception:
            return False

    # -- System information ------------------------------------------------

    def get_power_status(self) -> Tuple[bool, int]:
        status = _SYSTEM_POWER_STATUS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            ac = False if status.ACLineStatus == 255 else bool(status.ACLineStatus)
            pct = -1 if status.BatteryLifePercent == 255 else int(status.BatteryLifePercent)
            return ac, pct
        return False, -1

    def get_idle_seconds(self) -> float:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if _user32.GetLastInputInfo(ctypes.byref(lii)):
            tick = ctypes.windll.kernel32.GetTickCount()
            return max((tick - lii.dwTime) / 1000.0, 0.0)
        return 0.0

    # -- Global hotkey -----------------------------------------------------

    def validate_shortcut(self, shortcut: str) -> None:
        _parse_shortcut(shortcut)  # raises ValueError on failure

    def register_hotkey(self, shortcut: str, key_id: int,
                        callback: Callable) -> Optional[_WinHotkeyHandle]:
        try:
            modifiers, vk = _parse_shortcut(shortcut)
        except ValueError as exc:
            log.error("Invalid shortcut: %s", exc)
            return None
        handle = _WinHotkeyHandle(key_id, modifiers, vk, callback)
        handle.start()
        log.info("Registered global hotkey: %s", shortcut)
        return handle

    def unregister_hotkey(self, handle) -> None:
        if handle is not None:
            handle.stop()

    # -- Window-event hooks ------------------------------------------------

    def register_window_event_hook(self, callback: Callable) -> None:
        @WinEventProcType
        def _proc(hWinEventHook, event, hwnd, idObject, idChild, idEventThread, dwmsEventTime):
            if idObject == 0:  # OBJID_WINDOW
                callback(event, hwnd)

        _active_callbacks.append(_proc)
        for evt in (EVENT_OBJECT_CREATE, EVENT_OBJECT_DESTROY, EVENT_OBJECT_SHOW):
            hook = _user32.SetWinEventHook(evt, evt, 0, _proc, 0, 0, WINEVENT_OUTOFCONTEXT)
            if hook:
                _active_hooks.append(hook)

    def unregister_all_hooks(self) -> None:
        for hook in _active_hooks:
            _user32.UnhookWinEvent(hook)
        _active_hooks.clear()
        _active_callbacks.clear()
