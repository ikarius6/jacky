from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer, QPoint, QRectF
from PyQt6.QtGui import QPainter, QColor, QFont, QPainterPath, QBrush, QPen

from utils.dwm_helpers import remove_dwm_border


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

    def show_message(self, text: str, anchor_x: int, anchor_y: int, timeout_ms: int = 5000):
        """Show a speech bubble with text, anchored above the given point."""
        self._text = text
        self._anchor = QPoint(anchor_x, anchor_y)
        self._recalculate_size()
        self._reposition()
        self.show()
        self._remove_dwm_border()
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
        """Position the bubble so the pointer points at the anchor."""
        w = self.width()
        h = self.height()
        x = self._anchor.x() - w // 2
        y = self._anchor.y() - h
        # Keep on screen
        from utils.win32_helpers import get_screen_size
        try:
            sw, sh = get_screen_size()
            x = max(0, min(x, sw - w))
            y = max(0, y)
        except Exception:
            pass
        self.move(x, y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        bubble_h = h - self.POINTER_SIZE

        # Draw bubble body
        path = QPainterPath()
        rect = QRectF(1, 1, w - 2, bubble_h - 2)
        path.addRoundedRect(rect, self.BORDER_RADIUS, self.BORDER_RADIUS)

        # Draw pointer (small triangle at bottom center)
        cx = w // 2
        path.moveTo(cx - self.POINTER_SIZE, bubble_h - 1)
        path.lineTo(cx, h - 1)
        path.lineTo(cx + self.POINTER_SIZE, bubble_h - 1)

        painter.setBrush(QBrush(self.BUBBLE_COLOR))
        painter.setPen(QPen(self.BORDER_COLOR, 1.5))
        painter.drawPath(path)

        # Draw text
        painter.setPen(QPen(self.TEXT_COLOR))
        painter.setFont(self._font)
        text_rect = QRectF(
            self.PADDING, self.PADDING,
            w - 2 * self.PADDING, bubble_h - 2 * self.PADDING
        )
        painter.drawText(text_rect, Qt.TextFlag.TextWordWrap, self._text)
        painter.end()

    def _remove_dwm_border(self):
        """Use Windows DWM API to remove the shadow/border around the window."""
        remove_dwm_border(int(self.winId()))

    def mousePressEvent(self, event):
        """Click the bubble to dismiss it."""
        self.hide()
