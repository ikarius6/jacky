from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QKeyEvent


class KeyBindingInput(QLineEdit):
    """A QLineEdit that captures key combinations instead of typing text."""

    keySequenceChanged = pyqtSignal(QKeySequence)

    # Keys that don't make sense alone as a shortcut
    MODIFIER_KEYS = {
        Qt.Key.Key_Control, Qt.Key.Key_Shift,
        Qt.Key.Key_Alt, Qt.Key.Key_Meta,
        Qt.Key.Key_unknown,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sequence: QKeySequence | None = None
        self.setReadOnly(True)
        self.setPlaceholderText("Click and press a key combination...")

    # ── public API ──────────────────────────────────────────────────────────

    @property
    def sequence(self) -> QKeySequence | None:
        return self._sequence

    def set_shortcut(self, shortcut_str: str):
        """Initialise from a config-style string like 'ctrl+shift+space'."""
        if not shortcut_str:
            self.clear_binding()
            return
        # Title-case each part so QKeySequence can parse it
        normalised = "+".join(p.strip().capitalize() for p in shortcut_str.split("+"))
        seq = QKeySequence.fromString(normalised, QKeySequence.SequenceFormat.PortableText)
        if seq.isEmpty():
            self.setText(shortcut_str)  # show raw string as fallback
            self._sequence = None
        else:
            self._sequence = seq
            self.setText(seq.toString(QKeySequence.SequenceFormat.NativeText))

    def shortcut_config_string(self) -> str:
        """Return the current key combination in config format (e.g. 'ctrl+shift+space')."""
        if self._sequence is None:
            return ""
        portable = self._sequence.toString(QKeySequence.SequenceFormat.PortableText)
        return portable.lower().replace(" ", "")

    def clear_binding(self):
        self._sequence = None
        self.clear()
        self.setPlaceholderText("Click and press a key combination...")

    # ── internals ───────────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()

        if key == Qt.Key.Key_Escape:
            self.clear_binding()
            return

        if key in self.MODIFIER_KEYS:
            return  # wait for a non-modifier key

        # Build int combination: modifiers | key
        mods = event.modifiers().value
        combo = mods | key

        self._sequence = QKeySequence(combo)
        self.setText(self._sequence.toString(QKeySequence.SequenceFormat.NativeText))
        self.keySequenceChanged.emit(self._sequence)

    # Swallow key release so the widget stays focused correctly
    def keyReleaseEvent(self, event):
        pass
