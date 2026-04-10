import threading
import ctypes
import ctypes.wintypes
import logging
from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger("interaction.hotkey")

user32 = ctypes.windll.user32
WM_HOTKEY = 0x0312

# Standard Windows Modifiers
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# Mapping of human-readable modifier names to Windows constants
_MOD_MAP = {
    "ctrl":    MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift":   MOD_SHIFT,
    "alt":     MOD_ALT,
    "win":     MOD_WIN,
    "super":   MOD_WIN,
}

# Mapping of human-readable key names to Windows virtual-key codes
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

# Add single alphanumeric keys (A-Z => 0x41-0x5A, 0-9 => 0x30-0x39)
for c in range(ord('a'), ord('z') + 1):
    _VK_MAP[chr(c)] = c - 32  # VK codes for A-Z are uppercase ASCII values
for c in range(0, 10):
    _VK_MAP[str(c)] = 0x30 + c


def parse_shortcut(shortcut: str) -> tuple[int, int]:
    """Parse a shortcut string like 'ctrl+shift+space' into (modifiers, vk).

    Returns (modifiers_flags, virtual_key_code).
    Raises ValueError if the shortcut cannot be parsed.
    """
    parts = [p.strip().lower() for p in shortcut.split("+")]
    if not parts:
        raise ValueError(f"Empty shortcut string: {shortcut!r}")

    modifiers = 0
    vk = 0
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

    if key_part in _VK_MAP:
        vk = _VK_MAP[key_part]
    else:
        raise ValueError(f"Unknown key {key_part!r} in shortcut: {shortcut!r}")

    return modifiers, vk


class GlobalHotkey(QObject):
    """
    Registers a system-wide global hotkey on Windows using ctypes.
    Emits the 'pressed' pyqtSignal when triggered.
    """
    pressed = pyqtSignal()
    
    def __init__(self, shortcut: str = "ctrl+shift+space", key_id: int = 1):
        super().__init__()
        self._key_id = key_id
        self._shortcut = shortcut
        self._modifiers, self._vk = parse_shortcut(shortcut)
        self._running = False
        self._thread = None
        self._thread_id = None
        
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        
    def _run_loop(self):
        # Must register on the same thread that pumps messages
        # Add MOD_NOREPEAT to prevent the hotkey from firing repeatedly if the user holds it down.
        if not user32.RegisterHotKey(None, self._key_id, self._modifiers | MOD_NOREPEAT, self._vk):
            log.error("Unable to register global hotkey %s", self._shortcut)
            return
        
        log.info("Registered global hotkey: %s", self._shortcut)
        self._thread_id = threading.current_thread().native_id
            
        try:
            msg = ctypes.wintypes.MSG()
            while self._running:
                bRet = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if bRet <= 0:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == self._key_id:
                    self.pressed.emit()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, self._key_id)
            self._thread_id = None
            
    def stop(self):
        self._running = False
        if self._thread and self._thread_id:
            # Post a null message to unblock GetMessageW
            user32.PostThreadMessageW(self._thread_id, 0, 0, 0)

    def update_shortcut(self, shortcut: str):
        """Re-register the global hotkey with a new shortcut string.

        Stops the current listener, parses the new shortcut, and restarts.
        """
        if shortcut == self._shortcut:
            return
        try:
            modifiers, vk = parse_shortcut(shortcut)
        except ValueError:
            log.error("Invalid shortcut %r, keeping current: %s", shortcut, self._shortcut)
            return
        self.stop()
        # Wait for the old thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._shortcut = shortcut
        self._modifiers = modifiers
        self._vk = vk
        self._running = False
        self.start()
