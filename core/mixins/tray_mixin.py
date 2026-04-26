"""TrayMixin — system tray, topmost reassertion, and click-through helpers."""

import sys
import logging

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QIcon, QPixmap, QAction

from speech.dialogue import get_line
from utils.i18n import t

log = logging.getLogger("pet_window")


class TrayMixin:
    """Mixin providing system-tray setup, topmost management, and click-through."""

    # ── Tray setup ────────────────────────────────────────────────────────────

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        self._update_tray_icon()
        self._tray.setToolTip(f"{self.pet.name} - Desktop Pet")

        tray_menu = QMenu()
        show_action = QAction(t("ui.tray_show", name=self.pet.name), tray_menu)
        show_action.triggered.connect(self._bring_to_front)
        tray_menu.addAction(show_action)

        settings_action = QAction(t("ui.tray_settings"), tray_menu)
        settings_action.triggered.connect(lambda: self._context_menu._open_settings())
        tray_menu.addAction(settings_action)

        tray_menu.addSeparator()
        quit_action = QAction(t("ui.tray_quit"), tray_menu)
        quit_action.triggered.connect(self.on_quit)
        tray_menu.addAction(quit_action)

        self._tray.setContextMenu(tray_menu)
        self._tray.show()

    def _update_tray_icon(self):
        """Set the tray icon to the character's first idle frame, scaled to 32x32."""
        idle_frame = self.animation.current_frame()
        if idle_frame and not idle_frame.isNull():
            icon_pm = idle_frame.scaled(
                32, 32,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            icon_pm = QPixmap(32, 32)
            icon_pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(icon_pm)
            p.setBrush(Qt.GlobalColor.cyan)
            p.drawEllipse(4, 4, 24, 24)
            p.end()
        self._tray.setIcon(QIcon(icon_pm))

    # ── Window management ─────────────────────────────────────────────────────

    def _bring_to_front(self):
        self.show()
        self.raise_()
        self._reassert_topmost()

    def _reassert_topmost(self):
        """Re-assert HWND_TOPMOST via Win32 — guards against z-order demotion.

        On macOS we skip self.raise_() because it activates the app and steals
        focus from the user. The NSFloatingWindowLevel applied by set_topmost()
        is sufficient to keep the window above others without taking focus.
        """
        if not self._always_on_top:
            return
        try:
            if sys.platform != "darwin":
                self.raise_()
            from pal import set_topmost
            hwnd = int(self.winId())
            set_topmost(hwnd)
        except Exception:
            pass

    def set_click_through(self, click_through: bool):
        """Temporarily make the pet window and its speech bubble transparent to mouse clicks."""
        from pal import set_window_click_through
        set_window_click_through(int(self.winId()), click_through)
        if self._bubble:
            set_window_click_through(int(self._bubble.winId()), click_through)
        QApplication.processEvents()
