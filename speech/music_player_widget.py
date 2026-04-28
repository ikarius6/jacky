"""MusicPlayerWidget — compact floating media player controls.

A frameless floating widget with prev / play-pause / next buttons that follows
the pet, similar to ConfirmButtons.  Shown while music mode is active.

Sprite-based buttons are loaded from ``assets/music_buttons.png`` (512×256,
4 columns × 2 rows, each cell 128×128).  Row 0 = normal, Row 1 = pressed.
Column order: prev, next, play, pause.
Falls back to text symbols (⏮ ▶ ⏭) when the spritesheet is missing.
"""

import os
import sys
import logging

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt, QPoint, QSize, pyqtSignal
from PyQt6.QtGui import QPixmap, QIcon

from pal import remove_dwm_border, set_topmost

log = logging.getLogger("music_player_widget")

_SHEET_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           "assets", "music_buttons.png")
_CELL = 128                     # pixel size of each cell in the spritesheet
_ICON_DISPLAY = 40              # rendered icon size inside the button (px)
_BTN_SIZE = 48                  # button widget size (px)
_PLAY_BTN_SIZE = 56             # slightly larger for the center button

# Column indices in the spritesheet
_COL_PREV  = 0
_COL_NEXT  = 1
_COL_PLAY  = 2
_COL_PAUSE = 3


def _load_sprites() -> dict[str, tuple[QPixmap, QPixmap]] | None:
    """Load spritesheet and return {name: (normal, pressed)} or None."""
    if not os.path.isfile(_SHEET_PATH):
        return None
    sheet = QPixmap(_SHEET_PATH)
    if sheet.isNull():
        log.warning("Failed to load spritesheet %s", _SHEET_PATH)
        return None

    def _crop(col: int, row: int) -> QPixmap:
        return sheet.copy(col * _CELL, row * _CELL, _CELL, _CELL)

    return {
        "prev":  (_crop(_COL_PREV,  0), _crop(_COL_PREV,  1)),
        "next":  (_crop(_COL_NEXT,  0), _crop(_COL_NEXT,  1)),
        "play":  (_crop(_COL_PLAY,  0), _crop(_COL_PLAY,  1)),
        "pause": (_crop(_COL_PAUSE, 0), _crop(_COL_PAUSE, 1)),
    }


def _icon_from_pair(normal: QPixmap, pressed: QPixmap) -> QIcon:
    """Build a QIcon with Normal and Active/Pressed modes."""
    icon = QIcon()
    icon.addPixmap(normal, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(pressed, QIcon.Mode.Active, QIcon.State.Off)
    return icon


class MusicPlayerWidget(QWidget):
    """Floating mini media player with prev/play-pause/next buttons."""

    prev_clicked = pyqtSignal()
    play_pause_clicked = pyqtSignal()
    next_clicked = pyqtSignal()

    # Fallback text-button stylesheet (used when spritesheet is missing)
    _BTN_STYLE = """
        QPushButton {{
            background-color: {bg};
            color: {fg};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 2px 8px;
            font-size: {font_size};
            font-weight: bold;
            min-width: 28px;
            min-height: 28px;
        }}
        QPushButton:hover {{
            background-color: {hover};
        }}
        QPushButton:pressed {{
            background-color: {pressed};
        }}
    """

    _SPRITE_BTN_STYLE = """
        QPushButton {{
            background: transparent;
            border: none;
            padding: 0px;
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
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet("background: transparent;")

        self._is_playing = False
        self._anchor = QPoint(0, 0)
        self._pet_height = 0

        # Try loading sprite assets
        self._sprites = _load_sprites()
        self._use_sprites = self._sprites is not None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        if self._use_sprites:
            self._btn_prev = self._make_sprite_btn(
                self._sprites["prev"], _BTN_SIZE)
            self._btn_play = self._make_sprite_btn(
                self._sprites["play"], _PLAY_BTN_SIZE)
            self._btn_next = self._make_sprite_btn(
                self._sprites["next"], _BTN_SIZE)
        else:
            self._btn_prev = QPushButton("⏮")
            self._btn_prev.setStyleSheet(self._side_btn_style())
            self._btn_play = QPushButton("▶")
            self._btn_play.setStyleSheet(self._play_btn_style())
            self._btn_next = QPushButton("⏭")
            self._btn_next.setStyleSheet(self._side_btn_style())

        for btn in (self._btn_prev, self._btn_play, self._btn_next):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._btn_prev.clicked.connect(self.prev_clicked.emit)
        self._btn_play.clicked.connect(self.play_pause_clicked.emit)
        self._btn_next.clicked.connect(self.next_clicked.emit)

        layout.addWidget(self._btn_prev)
        layout.addWidget(self._btn_play)
        layout.addWidget(self._btn_next)

    # ── Sprite helpers ─────────────────────────────────────────────────────────

    def _make_sprite_btn(self, pair: tuple[QPixmap, QPixmap],
                         size: int) -> QPushButton:
        """Create a QPushButton with an icon from a (normal, pressed) pair."""
        btn = QPushButton()
        btn.setIcon(_icon_from_pair(*pair))
        btn.setIconSize(QSize(size, size))
        btn.setFixedSize(QSize(size, size))
        btn.setStyleSheet(self._SPRITE_BTN_STYLE)
        return btn

    # ── Fallback text styling ──────────────────────────────────────────────────

    def _side_btn_style(self) -> str:
        return self._BTN_STYLE.format(
            bg="#FFF8F0", fg="#5A3E2B", border="#DDB892",
            hover="#FFDDB5", pressed="#FFD0A0", font_size="13px",
        )

    def _play_btn_style(self) -> str:
        return self._BTN_STYLE.format(
            bg="#FFDDB5", fg="#5A3E2B", border="#DDB892",
            hover="#FFD0A0", pressed="#E8913A", font_size="15px",
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def update_play_state(self, is_playing: bool):
        """Toggle the play/pause icon based on playback state."""
        if is_playing == self._is_playing:
            return
        self._is_playing = is_playing
        if self._use_sprites:
            pair = self._sprites["pause"] if is_playing else self._sprites["play"]
            self._btn_play.setIcon(_icon_from_pair(*pair))
        else:
            self._btn_play.setText("⏸" if is_playing else "▶")

    def show_at(self, anchor_x: int, anchor_y: int, pet_height: int = 0):
        """Show the player anchored below the pet sprite."""
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
