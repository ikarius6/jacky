import ctypes
import ctypes.wintypes as wintypes
import time
from typing import Dict, List, Tuple, Optional, Callable

import win32gui
import win32con
import win32api
import win32process

# Cache: pid -> (process_name, timestamp)
_process_name_cache: Dict[int, Tuple[str, float]] = {}
_PROCESS_CACHE_TTL = 30.0  # seconds


def get_taskbar_rect() -> Tuple[int, int, int, int]:
    """Return (left, top, right, bottom) of the Windows taskbar."""
    hwnd = win32gui.FindWindow("Shell_TrayWnd", None)
    if hwnd:
        return win32gui.GetWindowRect(hwnd)
    # Fallback: assume taskbar at bottom, 48px tall
    screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    return (0, screen_h - 48, screen_w, screen_h)


def get_screen_size() -> Tuple[int, int]:
    """Return (width, height) of the primary monitor."""
    w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    return (w, h)


def get_work_area() -> Tuple[int, int, int, int]:
    """Return (left, top, right, bottom) of the usable desktop area (excluding taskbar)."""
    rect = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(
        0x0030,  # SPI_GETWORKAREA
        0,
        ctypes.byref(rect),
        0,
    )
    return (rect.left, rect.top, rect.right, rect.bottom)


class WindowInfo:
    """Info about a visible window."""
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


def get_visible_windows() -> List[WindowInfo]:
    """Enumerate all visible, non-minimized top-level windows."""
    windows = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return True
        # Skip our own window and certain system windows
        class_name = win32gui.GetClassName(hwnd)
        skip_classes = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman",
                        "WorkerW", "Windows.UI.Core.CoreWindow"}
        if class_name in skip_classes:
            return True

        try:
            rect = win32gui.GetWindowRect(hwnd)
        except Exception:
            return True

        placement = win32gui.GetWindowPlacement(hwnd)
        is_maximized = placement[1] == win32con.SW_SHOWMAXIMIZED
        is_minimized = placement[1] == win32con.SW_SHOWMINIMIZED

        if is_minimized:
            return True

        process_name = _get_process_name(hwnd)

        windows.append(WindowInfo(
            hwnd=hwnd,
            title=title,
            rect=rect,
            is_maximized=is_maximized,
            is_minimized=is_minimized,
            process_name=process_name,
        ))
        return True

    win32gui.EnumWindows(callback, None)
    return windows


def get_foreground_window() -> Optional[WindowInfo]:
    """Get the currently active foreground window."""
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
    is_maximized = placement[1] == win32con.SW_SHOWMAXIMIZED
    is_minimized = placement[1] == win32con.SW_SHOWMINIMIZED
    return WindowInfo(hwnd=hwnd, title=title, rect=rect,
                      is_maximized=is_maximized, is_minimized=is_minimized,
                      process_name=_get_process_name(hwnd))


def move_window(hwnd: int, dx: int, dy: int) -> bool:
    """Nudge a window by (dx, dy) pixels. Returns True on success."""
    try:
        rect = win32gui.GetWindowRect(hwnd)
        new_x = rect[0] + dx
        new_y = rect[1] + dy
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        win32gui.SetWindowPos(
            hwnd, None, new_x, new_y, w, h,
            win32con.SWP_NOZORDER | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
        )
        return True
    except Exception:
        return False


def set_window_pos(hwnd: int, x: int, y: int) -> bool:
    """Move a window to an absolute position. Returns True on success."""
    try:
        rect = win32gui.GetWindowRect(hwnd)
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        win32gui.SetWindowPos(
            hwnd, None, x, y, w, h,
            win32con.SWP_NOZORDER | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
        )
        return True
    except Exception:
        return False


def resize_window(hwnd: int, dw: int, dh: int) -> bool:
    """Resize a window by (dw, dh) pixels. Returns True on success."""
    try:
        rect = win32gui.GetWindowRect(hwnd)
        x = rect[0]
        y = rect[1]
        new_w = max(200, (rect[2] - rect[0]) + dw)
        new_h = max(150, (rect[3] - rect[1]) + dh)
        win32gui.SetWindowPos(
            hwnd, None, x, y, new_w, new_h,
            win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
        )
        return True
    except Exception:
        return False


def minimize_window(hwnd: int) -> bool:
    """Minimize a window to the taskbar. Returns True on success."""
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        return True
    except Exception:
        return False


def flash_window(hwnd: int, count: int = 3) -> bool:
    """Flash a window's taskbar button to get attention. Returns True on success."""
    try:
        import ctypes

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
        fi.hwnd = hwnd
        fi.dwFlags = FLASHW_ALL
        fi.uCount = count
        fi.dwTimeout = 0
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(fi))
        return True
    except Exception:
        return False


def set_foreground_window(hwnd: int) -> bool:
    """Bring a window to the foreground. Returns True on success."""
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def tile_windows(hwnds: List[int]) -> bool:
    """Tile a list of windows in a grid across the work area. Returns True on success."""
    if not hwnds:
        return False
    try:
        work = get_work_area()
        wa_x, wa_y, wa_right, wa_bottom = work
        wa_w = wa_right - wa_x
        wa_h = wa_bottom - wa_y

        n = len(hwnds)
        cols = int(n ** 0.5)
        if cols < 1:
            cols = 1
        rows = (n + cols - 1) // cols
        cell_w = wa_w // cols
        cell_h = wa_h // rows

        for i, hwnd in enumerate(hwnds):
            col = i % cols
            row = i // cols
            x = wa_x + col * cell_w
            y = wa_y + row * cell_h
            win32gui.SetWindowPos(
                hwnd, None, x, y, cell_w, cell_h,
                win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
            )
        return True
    except Exception:
        return False


# --- WinEvent hook for window create/destroy ---

_user32 = ctypes.windll.user32

# WinEventProc callback type
WinEventProcType = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,  # hWinEventHook
    wintypes.DWORD,   # event
    wintypes.HWND,    # hwnd
    ctypes.c_long,    # idObject
    ctypes.c_long,    # idChild
    wintypes.DWORD,   # idEventThread
    wintypes.DWORD,   # dwmsEventTime
)

EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW = 0x8002
WINEVENT_OUTOFCONTEXT = 0x0000

_active_hooks = []
_active_callbacks = []  # prevent GC


def register_window_event_hook(callback: Callable[[int, int], None]):
    """
    Register a hook for window create/show/destroy events.
    callback(event_type, hwnd) is called on each event.
    event_type is one of EVENT_OBJECT_CREATE, EVENT_OBJECT_DESTROY, EVENT_OBJECT_SHOW.
    """
    @WinEventProcType
    def _win_event_proc(hWinEventHook, event, hwnd, idObject, idChild, idEventThread, dwmsEventTime):
        if idObject == 0:  # OBJID_WINDOW
            callback(event, hwnd)

    _active_callbacks.append(_win_event_proc)

    for event in (EVENT_OBJECT_CREATE, EVENT_OBJECT_DESTROY, EVENT_OBJECT_SHOW):
        hook = _user32.SetWinEventHook(
            event, event,
            0,
            _win_event_proc,
            0, 0,
            WINEVENT_OUTOFCONTEXT,
        )
        if hook:
            _active_hooks.append(hook)


def unregister_all_hooks():
    """Unregister all window event hooks."""
    for hook in _active_hooks:
        _user32.UnhookWinEvent(hook)
    _active_hooks.clear()
    _active_callbacks.clear()
