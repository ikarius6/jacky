"""WindowMixin — screen geometry, DPI scale, and multi-monitor helpers."""

import time
import logging

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPoint

from interaction.context_menu import DEFAULT_PERMISSIONS, PERMISSION_DEFS

log = logging.getLogger("pet_window")


class WindowMixin:
    """Mixin providing screen-geometry, DPI scale, bounds helpers, and window-awareness setup."""

    # ── DPI / position ────────────────────────────────────────────────────────

    def _apply_dpi_scale(self):
        """Pass the screen DPI scale to the movement engine for coord conversion.

        On macOS, CG window coordinates are already in logical points that
        match Qt coords, so no scaling is needed (scale stays 1.0).
        On Windows, GetWindowRect returns physical pixels that must be divided
        by devicePixelRatio.
        """
        from pal import backend
        if backend.coords_are_physical:
            screen = self._current_screen()
            if screen:
                self.movement.set_dpi_scale(screen.devicePixelRatio())
        else:
            self.movement.set_dpi_scale(1.0)

    def _init_position(self):
        self._refresh_screen_bounds()
        geo = self._screen_geo()
        x = geo.x() + geo.width() // 2 - self._sprite_size // 2
        y = geo.y() + geo.height() - self._sprite_size
        self.move(x, y)
        self.movement.set_position(x, y)
        log.info("INIT_POS (%d,%d) screen=%s", x, y, (geo.x(), geo.y(), geo.width(), geo.height()))

    # ── Screen helpers ────────────────────────────────────────────────────────

    def _current_screen(self):
        """Return the QScreen that contains the pet's center point."""
        center = QPoint(self.x() + self._sprite_size // 2,
                        self.y() + self._sprite_size // 2)
        screen = QApplication.screenAt(center)
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen

    def _screen_geo(self):
        """Return the available geometry of the screen Jacky is currently on."""
        screen = self._current_screen()
        if screen:
            return screen.availableGeometry()
        from PyQt6.QtCore import QRect
        return QRect(0, 0, 1920, 1080)

    def _virtual_desktop_geo(self):
        """Return the bounding rect of all screens' available geometries."""
        from PyQt6.QtCore import QRect
        screens = QApplication.screens()
        if not screens:
            return QRect(0, 0, 1920, 1080)
        result = screens[0].availableGeometry()
        for s in screens[1:]:
            result = result.united(s.availableGeometry())
        return result

    # ── Screen signal wiring ──────────────────────────────────────────────────

    def _connect_screen_signals(self):
        """Listen for screen geometry changes to invalidate cached bounds."""
        for screen in QApplication.screens():
            screen.geometryChanged.connect(self._on_screen_geometry_changed)
            screen.availableGeometryChanged.connect(self._on_screen_geometry_changed)
        QApplication.instance().screenAdded.connect(self._on_screens_changed)
        QApplication.instance().screenRemoved.connect(self._on_screens_changed)

    def _on_screen_geometry_changed(self):
        self._bounds_dirty = True

    def _on_screens_changed(self, screen):
        self._bounds_dirty = True
        self._connect_screen_signals()

    # ── Bounds refresh ────────────────────────────────────────────────────────

    def _refresh_screen_bounds(self):
        """Push virtual desktop bounds into the movement engine (multi-monitor)."""
        vgeo = self._virtual_desktop_geo()
        self.movement.update_bounds(
            vgeo.x(), vgeo.y(),
            vgeo.x() + vgeo.width(),
            vgeo.y() + vgeo.height(),
        )
        geo = self._screen_geo()
        self.movement.update_current_screen(
            geo.x(), geo.y(),
            geo.x() + geo.width(),
            geo.y() + geo.height(),
        )
        rects = []
        for s in QApplication.screens():
            g = s.availableGeometry()
            rects.append((g.x(), g.y(), g.x() + g.width(), g.y() + g.height()))
        self.movement.update_screen_rects(rects)
        self._last_bounds_refresh = time.monotonic()
        self._bounds_dirty = False

    def _maybe_refresh_screen_bounds(self):
        """Throttled screen-bounds refresh: updates at most every 2s, or immediately if dirty."""
        now = time.monotonic()
        if self._bounds_dirty or (now - self._last_bounds_refresh) >= self._BOUNDS_REFRESH_INTERVAL_S:
            self._refresh_screen_bounds()

    # ── Window-awareness setup ────────────────────────────────────────────────

    def _setup_window_awareness(self):
        if not self._config.get("window_interaction_enabled", True):
            return
        perms = self._config.get("permissions", DEFAULT_PERMISSIONS)
        any_destructive = any(
            perms.get(p[0], True) for p in PERMISSION_DEFS if p[3] == "destructive"
        )
        self._window_awareness.set_push_enabled(
            self._config.get("window_push_enabled", True) and any_destructive
        )
        self._window_awareness.set_callbacks(
            on_opened=self._window_interactions.on_window_opened,
            on_closed=self._window_interactions.on_window_closed,
        )
        self._window_awareness.start(poll_interval_ms=3000)
