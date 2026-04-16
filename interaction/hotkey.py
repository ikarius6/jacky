import logging
from PyQt6.QtCore import QObject, pyqtSignal

from pal import backend

log = logging.getLogger("interaction.hotkey")


def parse_shortcut(shortcut: str) -> tuple[int, int]:
    """Validate a shortcut string like ``'ctrl+shift+space'``.

    Delegates to the platform backend.  Raises :class:`ValueError` on failure.
    Returns a platform-specific ``(modifiers, vk)`` tuple.
    """
    backend.validate_shortcut(shortcut)        # raises ValueError if bad
    # Return a dummy tuple — callers only need this for validation
    return (0, 0)


class GlobalHotkey(QObject):
    """Cross-platform global hotkey via the PAL backend.

    Emits the ``pressed`` signal when the registered shortcut is activated.
    """
    pressed = pyqtSignal()

    def __init__(self, shortcut: str = "ctrl+shift+space", key_id: int = 1):
        super().__init__()
        self._key_id = key_id
        self._shortcut = shortcut
        self._handle = None

    def start(self):
        if self._handle is not None:
            return
        self._handle = backend.register_hotkey(
            self._shortcut, self._key_id, self.pressed.emit,
        )
        if self._handle is None:
            log.error("Unable to register global hotkey %s", self._shortcut)

    def stop(self):
        if self._handle is not None:
            backend.unregister_hotkey(self._handle)
            # Wait for the message-loop thread to exit
            if hasattr(self._handle, "join"):
                self._handle.join(timeout=2.0)
            self._handle = None

    def update_shortcut(self, shortcut: str):
        """Re-register the global hotkey with a new shortcut string.

        Validates *before* stopping the current listener so that an invalid
        shortcut doesn't leave the hotkey unregistered.
        """
        if shortcut == self._shortcut:
            return
        try:
            backend.validate_shortcut(shortcut)
        except ValueError:
            log.error("Invalid shortcut %r, keeping current: %s", shortcut, self._shortcut)
            return
        self.stop()
        self._shortcut = shortcut
        self.start()
