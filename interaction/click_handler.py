import time

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QMouseEvent

_RAPID_CLICK_COUNT = 10   # clicks needed to trigger dizzy
_RAPID_CLICK_WINDOW = 3.0  # seconds
_LONG_DRAG_SECONDS = 5.0   # drag duration to trigger dizzy


class ClickHandler:
    """Handles mouse interactions on the pet window: click, drag, right-click."""

    def __init__(self, pet_window):
        self._pet_window = pet_window
        self._dragging = False
        self._drag_offset = QPoint(0, 0)
        self._click_start = QPoint(0, 0)
        self._drag_threshold = 5  # pixels before a click becomes a drag

        # Easter egg: rapid click meltdown
        self._click_times: list[float] = []
        self._drag_start_time: float = 0.0

    def handle_press(self, event: QMouseEvent):
        """Called from pet_window.mousePressEvent."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_start = event.globalPosition().toPoint()
            self._drag_offset = event.globalPosition().toPoint() - self._pet_window.pos()
            self._dragging = False
        elif event.button() == Qt.MouseButton.RightButton:
            self._pet_window.show_context_menu(event.globalPosition().toPoint())

    def handle_move(self, event: QMouseEvent):
        """Called from pet_window.mouseMoveEvent."""
        if event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._click_start
            if not self._dragging and (abs(delta.x()) > self._drag_threshold or abs(delta.y()) > self._drag_threshold):
                self._dragging = True
                self._drag_start_time = time.monotonic()
                self._pet_window.on_drag_start()

            if self._dragging:
                new_pos = event.globalPosition().toPoint() - self._drag_offset
                self._pet_window.move(new_pos)
                self._pet_window._update_bubble_pos()

    def handle_release(self, event: QMouseEvent):
        """Called from pet_window.mouseReleaseEvent."""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging:
                self._dragging = False
                drag_duration = time.monotonic() - self._drag_start_time
                self._pet_window.on_drag_end()
                if drag_duration >= _LONG_DRAG_SECONDS:
                    self._pet_window.on_dizzy()
            else:
                now = time.monotonic()
                self._click_times.append(now)
                cutoff = now - _RAPID_CLICK_WINDOW
                self._click_times = [t for t in self._click_times if t > cutoff]
                if len(self._click_times) >= _RAPID_CLICK_COUNT:
                    self._click_times.clear()
                    self._pet_window.on_dizzy()
                else:
                    self._pet_window.on_pet_clicked()
