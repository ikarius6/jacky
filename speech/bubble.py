import sys
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer, QPoint, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont, QPainterPath, QBrush, QPen

from pal import remove_dwm_border, set_topmost


class SpeechBubble(QWidget):
    """Frameless transparent speech bubble that follows the pet."""

    BUBBLE_COLOR = QColor(255, 255, 255, 230)
    BORDER_COLOR = QColor(80, 80, 80, 200)
    TEXT_COLOR = QColor(40, 40, 40)
    PADDING = 12
    POINTER_SIZE = 10
    BORDER_RADIUS = 12
    MAX_WIDTH = 250

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._text = ""
        self._font = QFont("Segoe UI", 10)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self._anchor = QPoint(0, 0)  # Bottom center of bubble points here
        self._flipped = False  # True = bubble below anchor (pointer on top)
        self._pet_height = 0  # height of pet sprite, set via show_message

        # Thinking animation
        self._thinking = False
        self._think_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._think_index = 0
        self._think_timer = QTimer(self)
        self._think_timer.setInterval(120)
        self._think_timer.timeout.connect(self._on_think_tick)

    def show_thinking(self, anchor_x: int, anchor_y: int, pet_height: int = 0):
        """Show an animated thinking indicator in the bubble."""
        self._thinking = True
        self._think_index = 0
        from utils.i18n import t
        self._text = t("ui.thinking") + " " + self._think_frames[0]
        self._anchor = QPoint(anchor_x, anchor_y)
        self._pet_height = pet_height
        self._recalculate_size()
        self._reposition()
        self.show()
        self._apply_platform_chrome()
        self.update()
        self._hide_timer.stop()
        self._think_timer.start()

    def hide(self):
        """Hide the bubble and ensure any running timers are stopped."""
        self._think_timer.stop()
        self._thinking = False
        super().hide()


    def _on_think_tick(self):
        """Advance the thinking animation."""
        self._think_index = (self._think_index + 1) % len(self._think_frames)
        from utils.i18n import t
        self._text = t("ui.thinking") + " " + self._think_frames[self._think_index]
        self.update()

    def show_message(self, text: str, anchor_x: int, anchor_y: int,
                     timeout_ms: int = 5000, pet_height: int = 0):
        """Show a speech bubble with text, anchored above the given point."""
        self._think_timer.stop()
        self._thinking = False
        self._text = text
        self._anchor = QPoint(anchor_x, anchor_y)
        self._pet_height = pet_height
        self._recalculate_size()
        self._reposition()
        self.show()
        self._apply_platform_chrome()
        self.update()
        self._hide_timer.stop()
        if timeout_ms > 0:
            self._hide_timer.start(timeout_ms)

    def update_position(self, anchor_x: int, anchor_y: int):
        """Update the anchor position (call when the pet moves)."""
        self._anchor = QPoint(anchor_x, anchor_y)
        if self.isVisible():
            self._reposition()

    def _recalculate_size(self):
        """Calculate the bubble size based on text content."""
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(self._font)
        text_rect = fm.boundingRect(
            0, 0, self.MAX_WIDTH - 2 * self.PADDING, 10000,
            Qt.TextFlag.TextWordWrap, self._text
        )
        w = min(text_rect.width() + 2 * self.PADDING + 4, self.MAX_WIDTH)
        h = text_rect.height() + 2 * self.PADDING + self.POINTER_SIZE + 4
        self.setFixedSize(max(w, 60), max(h, 40))

    def _reposition(self):
        """Position the bubble so the pointer points at the anchor.

        If the bubble would be clipped at the top of the screen, flip it
        below the pet instead.
        """
        w = self.width()
        h = self.height()
        x = self._anchor.x() - w // 2
        # Default: bubble above the anchor
        y_above = self._anchor.y() - h
        # Flipped: bubble below the pet
        y_below = self._anchor.y() + self._pet_height

        old_flipped = self._flipped
        self._flipped = y_above < 0
        y = y_below if self._flipped else y_above

        # Keep on screen horizontally
        from pal import get_screen_size
        try:
            sw, sh = get_screen_size()
            x = max(0, min(x, sw - w))
        except Exception:
            pass
        self.move(x, y)
        
        if old_flipped != self._flipped:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        ps = self.POINTER_SIZE
        bubble_h = h - ps

        path = QPainterPath()

        if self._flipped:
            # Pointer on top, bubble body below
            rect = QRectF(1, ps + 1, w - 2, bubble_h - 2)
            path.addRoundedRect(rect, self.BORDER_RADIUS, self.BORDER_RADIUS)
            cx = w // 2
            path.moveTo(cx - ps, ps + 1)
            path.lineTo(cx, 1)
            path.lineTo(cx + ps, ps + 1)
            text_rect = QRectF(
                self.PADDING, ps + self.PADDING,
                w - 2 * self.PADDING, bubble_h - 2 * self.PADDING
            )
        else:
            # Pointer on bottom (default), bubble body above
            rect = QRectF(1, 1, w - 2, bubble_h - 2)
            path.addRoundedRect(rect, self.BORDER_RADIUS, self.BORDER_RADIUS)
            cx = w // 2
            path.moveTo(cx - ps, bubble_h - 1)
            path.lineTo(cx, h - 1)
            path.lineTo(cx + ps, bubble_h - 1)
            text_rect = QRectF(
                self.PADDING, self.PADDING,
                w - 2 * self.PADDING, bubble_h - 2 * self.PADDING
            )

        painter.setBrush(QBrush(self.BUBBLE_COLOR))
        painter.setPen(QPen(self.BORDER_COLOR, 1.5))
        painter.drawPath(path)

        # Draw text
        painter.setPen(QPen(self.TEXT_COLOR))
        painter.setFont(self._font)
        painter.drawText(text_rect, Qt.TextFlag.TextWordWrap, self._text)
        painter.end()

    def _apply_platform_chrome(self):
        """Apply platform-specific window chrome.

        On Windows, remove the DWM shadow/border.
        On macOS, also set NSFloatingWindowLevel so the bubble truly floats
        above other windows without stealing focus (WA_ShowWithoutActivating
        prevents activation, but the NSWindow level must also be set natively).
        """
        wid = int(self.winId())
        remove_dwm_border(wid)  # no-op on macOS
        if sys.platform == "darwin":
            set_topmost(wid)

    # Keep old name in case any other code references it
    def _remove_dwm_border(self):
        self._apply_platform_chrome()

    def mousePressEvent(self, event):
        """Click the bubble to dismiss it."""
        self.hide()


class ConfirmButtons(QWidget):
    """Small floating widget with Yes/No buttons for organize confirmation.

    Shown alongside the speech bubble when the pet asks the user to confirm
    an action.  Provides a reliable GUI fallback when STT struggles with
    very short words like "sí" / "no".
    """

    confirmed = pyqtSignal(bool)  # True = yes, False = no

    BTN_STYLE = """
        QPushButton {{
            background-color: {bg};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 4px 14px;
            font-size: 13px;
            font-weight: bold;
            min-width: 54px;
        }}
        QPushButton:hover {{
            background-color: {hover};
        }}
        QPushButton:pressed {{
            background-color: {pressed};
        }}
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        from PyQt6.QtWidgets import QHBoxLayout, QPushButton
        from utils.i18n import t

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        self._btn_yes = QPushButton(t("ui.btn_yes"))
        self._btn_no = QPushButton(t("ui.btn_no"))

        self._btn_yes.setStyleSheet(self.BTN_STYLE.format(
            bg="#4CAF50", hover="#43A047", pressed="#388E3C"))
        self._btn_no.setStyleSheet(self.BTN_STYLE.format(
            bg="#F44336", hover="#E53935", pressed="#C62828"))

        self._btn_yes.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_no.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addWidget(self._btn_yes)
        layout.addWidget(self._btn_no)

        self._btn_yes.clicked.connect(lambda: self.confirmed.emit(True))
        self._btn_no.clicked.connect(lambda: self.confirmed.emit(False))

        self._anchor = QPoint(0, 0)
        self._pet_height = 0

    def show_at(self, anchor_x: int, anchor_y: int, pet_height: int = 0):
        """Show the buttons anchored below the pet sprite."""
        from utils.i18n import t
        self._btn_yes.setText(t("ui.btn_yes"))
        self._btn_no.setText(t("ui.btn_no"))
        self._anchor = QPoint(anchor_x, anchor_y)
        self._pet_height = pet_height
        self.adjustSize()
        self._reposition()
        self.show()
        wid = int(self.winId())
        remove_dwm_border(wid)
        if sys.platform == "darwin":
            set_topmost(wid)

    def update_position(self, anchor_x: int, anchor_y: int):
        """Update the anchor position (call when the pet moves)."""
        self._anchor = QPoint(anchor_x, anchor_y)
        if self.isVisible():
            self._reposition()

    def _reposition(self):
        w = self.width()
        x = self._anchor.x() - w // 2
        y = self._anchor.y() + self._pet_height + 4

        from pal import get_screen_size
        try:
            sw, sh = get_screen_size()
            x = max(0, min(x, sw - w))
            if y + self.height() > sh:
                y = self._anchor.y() - self.height() - 4
        except Exception:
            pass
        self.move(x, y)
