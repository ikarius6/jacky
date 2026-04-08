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

class GlobalHotkey(QObject):
    """
    Registers a system-wide global hotkey on Windows using ctypes.
    Emits the 'pressed' pyqtSignal when triggered.
    """
    pressed = pyqtSignal()
    
    def __init__(self, key_id=1, modifiers=MOD_CONTROL | MOD_SHIFT, vk=0x20): # default is Ctrl+Shift+Space
        super().__init__()
        self._key_id = key_id
        self._modifiers = modifiers
        self._vk = vk
        self._running = False
        self._thread = None
        
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
            log.error("Unable to register global hotkey Ctrl+Shift+Space")
            return
            
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
            
    def stop(self):
        self._running = False
        if self._thread and self._thread.native_id:
            # Post a null message to unblock GetMessageW
            user32.PostThreadMessageW(self._thread.native_id, 0, 0, 0)
