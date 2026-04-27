"""Collectible UI widgets: floating item, card popup, and collection panel."""

import sys
import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                             QPushButton, QDialog, QScrollArea, QFrame,
                             QGridLayout, QGraphicsOpacityEffect, QComboBox)
from PyQt6.QtCore import (Qt, QTimer, QPropertyAnimation, QEasingCurve,
                          pyqtSignal, QSize, QRectF)
from PyQt6.QtGui import (QPixmap, QPainter, QColor, QFont, QBrush, QPen,
                         QPainterPath, QLinearGradient, QImage)

from pal import remove_dwm_border, set_topmost
from utils.i18n import t

log = logging.getLogger(__name__)

# ── Sprite catalog — 30 items with display names and placeholder colors ──

SPRITE_CATALOG = {
    "rubber_duck":       ("Rubber Duck",        "#FFD700"),
    "sock":              ("Sock",               "#8B4513"),
    "yo_yo":             ("Yo-Yo",              "#FF4500"),
    "fidget_spinner":    ("Fidget Spinner",     "#00CED1"),
    "snow_globe":        ("Snow Globe",         "#87CEEB"),
    "ancient_scroll":    ("Ancient Scroll",     "#D2B48C"),
    "crystal_ball":      ("Crystal Ball",       "#9370DB"),
    "compass":           ("Compass",            "#B8860B"),
    "hourglass":         ("Hourglass",          "#DAA520"),
    "mysterious_key":    ("Mysterious Key",     "#808080"),
    "golden_taco":       ("Golden Taco",        "#FFB347"),
    "ancient_pizza":     ("Ancient Pizza Slice","#FF6347"),
    "enchanted_donut":   ("Enchanted Donut",    "#FF69B4"),
    "cursed_coffee":     ("Cursed Coffee",      "#6F4E37"),
    "rogue_chili":       ("Rogue Chili",        "#DC143C"),
    "floppy_disk":       ("Floppy Disk",        "#4169E1"),
    "broken_calculator": ("Broken Calculator",  "#2F4F4F"),
    "test_tube":         ("Test Tube",          "#7FFF00"),
    "old_phone":         ("Old Phone",          "#556B2F"),
    "pixel_heart":       ("Pixel Heart",        "#FF1493"),
    "four_leaf_clover":  ("Four Leaf Clover",   "#228B22"),
    "shooting_star":     ("Shooting Star",      "#FFD700"),
    "moon_fragment":     ("Moon Fragment",       "#C0C0C0"),
    "magic_mushroom":    ("Magic Mushroom",     "#FF00FF"),
    "tiny_dragon_egg":   ("Tiny Dragon Egg",    "#8B0000"),
    "rubber_chicken":    ("Rubber Chicken",     "#FFDAB9"),
    "tiny_crown":        ("Tiny Crown",         "#FFD700"),
    "lucky_coin":        ("Lucky Coin",         "#DAA520"),
    "infinite_die":      ("Infinite Die",       "#800080"),
    "jacky_plushie":     ("Jacky Plushie",      "#FF8C00"),
}

def get_sprite_display_name(sprite_key: str) -> str:
    """Return the localized display name for a sprite key.

    Looks up ``sprite_names.<key>`` in the current locale's
    ``collectibles.json``.  Falls back to the English name in
    SPRITE_CATALOG if the key is missing for the active language.
    """
    localized = t(f"sprite_names.{sprite_key}")
    # t() returns the raw key path when it can't find a match
    if localized != f"sprite_names.{sprite_key}":
        return localized
    entry = SPRITE_CATALOG.get(sprite_key)
    return entry[0] if entry else sprite_key


_RARITY_COLORS = {
    1: "#9E9E9E",  # common — gray
    2: "#4CAF50",  # uncommon — green
    3: "#2196F3",  # rare — blue
    4: "#9C27B0",  # epic — purple
    5: "#FF9800",  # legendary — orange/gold
}

_RARITY_LABELS = {
    1: "Common",
    2: "Uncommon",
    3: "Rare",
    4: "Epic",
    5: "Legendary",
}

_COLLECTIBLES_DIR = Path(__file__).resolve().parent.parent / "collectibles"


def get_sprite_pixmap(sprite_key: str, size: int = 48, glitch: bool = False) -> QPixmap:
    """Load a sprite PNG or generate a placeholder if missing.

    Args:
        sprite_key: The sprite identifier
        size: Target size in pixels
        glitch: If True, apply glitch distortion effect
    """
    sprite_path = _COLLECTIBLES_DIR / "sprites" / f"{sprite_key}.png"
    if sprite_path.exists():
        pix = QPixmap(str(sprite_path))
        if not pix.isNull():
            pix = pix.scaled(size, size,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
    else:
        # Generate placeholder: colored circle with first letter
        display_name, color = SPRITE_CATALOG.get(sprite_key, (sprite_key, "#888888"))
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(color)))
        p.setPen(QPen(QColor(color).darker(140), 2))
        p.drawEllipse(2, 2, size - 4, size - 4)
        p.setPen(QPen(QColor("white")))
        font = QFont("Segoe UI", size // 3, QFont.Weight.Bold)
        p.setFont(font)
        letter = display_name[0].upper()
        p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, letter)
        p.end()

    # Apply glitch distortion
    if glitch and not pix.isNull():
        from PyQt6.QtGui import QImage
        import random
        img = pix.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        iw, ih = img.width(), img.height()
        # Horizontal scanline shifts
        for row in range(0, ih, 4):
            if random.random() < 0.3:
                shift = random.randint(-3, 3)
                if shift == 0:
                    continue
                a = abs(shift)
                if a >= iw:
                    continue
                if shift > 0:
                    # Shift right: copy left portion, draw offset right
                    strip = img.copy(0, row, iw - a, 1)
                    painter = QPainter(img)
                    painter.drawImage(a, row, strip)
                    painter.end()
                else:
                    # Shift left: copy right portion, draw at x=0
                    strip = img.copy(a, row, iw - a, 1)
                    painter = QPainter(img)
                    painter.drawImage(0, row, strip)
                    painter.end()
        # XOR block artifacts
        max_block = max(4, iw // 6)
        if iw > 8 and ih > 8:
            for _ in range(3):
                bw = random.randint(4, max_block)
                bh = random.randint(4, max_block)
                bx = random.randint(0, iw - bw - 1)
                by = random.randint(0, ih - bh - 1)
                rect = img.copy(bx, by, bw, bh)
                dx = max(0, min(iw - bw, bx + random.randint(-2, 2)))
                dy = max(0, min(ih - bh, by + random.randint(-2, 2)))
                painter = QPainter(img)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Xor)
                painter.drawImage(dx, dy, rect)
                painter.end()
        pix = QPixmap.fromImage(img)

    return pix


def rarity_stars(rarity: int) -> str:
    """Return star string for a rarity level 1-5."""
    return "⭐" * max(1, min(5, rarity))


# ═══════════════════════════════════════════════════════════════════════════
# CollectibleItemWidget — the floating sprite on screen the user can click
# ═══════════════════════════════════════════════════════════════════════════

class CollectibleItemWidget(QWidget):
    """Transparent frameless window showing a collectible sprite on the desktop."""

    clicked = pyqtSignal(str)  # sprite_key

    ITEM_SIZE = 48
    DISMISS_MS = 5 * 60 * 1000  # 5 minutes

    def __init__(self, sprite_key: str, appearance_mode: str | None = None, parent=None):
        super().__init__(parent)
        self._sprite_key = sprite_key
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self.ITEM_SIZE + 20, self.ITEM_SIZE + 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._pixmap = get_sprite_pixmap(sprite_key, self.ITEM_SIZE, glitch=(appearance_mode == "glitch"))
        self._glow_pixmap = self._build_contour_glow()

        # Fade-in
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._fade_in = QPropertyAnimation(self._opacity, b"opacity")
        self._fade_in.setDuration(800)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Fade-out
        self._fade_out = QPropertyAnimation(self._opacity, b"opacity")
        self._fade_out.setDuration(1500)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(self._on_fade_out_done)

        # Auto-dismiss timer
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.dismiss)

        # Bounce animation (small vertical oscillation)
        self._bounce_timer = QTimer(self)
        self._bounce_timer.setInterval(80)
        self._bounce_offset = 0
        self._bounce_dir = 1
        self._base_y = 0
        self._bounce_timer.timeout.connect(self._bounce_tick)

    @property
    def sprite_key(self) -> str:
        return self._sprite_key

    def spawn_at(self, x: int, y: int):
        """Show the item at (x, y) with fade-in and start dismiss timer."""
        self._base_y = y
        self.move(x, y)
        self.show()
        wid = int(self.winId())
        remove_dwm_border(wid)
        if sys.platform == "darwin":
            set_topmost(wid)
        self._fade_in.start()
        self._dismiss_timer.start(self.DISMISS_MS)
        self._bounce_timer.start()

    def dismiss(self):
        """Start fade-out. On completion the widget is hidden and deleteLater'd."""
        self._dismiss_timer.stop()
        self._bounce_timer.stop()
        if self.isVisible():
            self._fade_out.start()

    def _on_fade_out_done(self):
        self.hide()
        self.deleteLater()

    def _bounce_tick(self):
        self._bounce_offset += self._bounce_dir
        if abs(self._bounce_offset) >= 3:
            self._bounce_dir = -self._bounce_dir
        self.move(self.x(), self._base_y + self._bounce_offset)

    def _build_contour_glow(self) -> QPixmap:
        """Build a glow pixmap that follows the sprite's alpha silhouette."""
        sw, sh = self._pixmap.width(), self._pixmap.height()
        if sw == 0 or sh == 0:
            return QPixmap()

        # Create gold silhouette masked by sprite alpha
        silhouette = QImage(sw, sh, QImage.Format.Format_ARGB32)
        silhouette.fill(QColor(255, 215, 0, 200))
        sp = QPainter(silhouette)
        sp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        sp.drawPixmap(0, 0, self._pixmap)
        sp.end()
        sil_pix = QPixmap.fromImage(silhouette)

        # Paint silhouette at multiple offsets to create a soft blur
        ww, wh = self.width(), self.height()
        canvas = QImage(ww, wh, QImage.Format.Format_ARGB32)
        canvas.fill(Qt.GlobalColor.transparent)
        ox = (ww - sw) // 2
        oy = (wh - sh) // 2
        spread = 8

        cp = QPainter(canvas)
        cp.setRenderHint(QPainter.RenderHint.Antialiasing)
        for dx in range(-spread, spread + 1):
            for dy in range(-spread, spread + 1):
                dist_sq = dx * dx + dy * dy
                if dist_sq <= spread * spread:
                    dist = dist_sq ** 0.5
                    cp.setOpacity(0.055 * (1.0 - dist / (spread + 1)))
                    cp.drawPixmap(ox + dx, oy + dy, sil_pix)
        cp.end()
        return QPixmap.fromImage(canvas)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Contour glow behind
        if not self._glow_pixmap.isNull():
            p.drawPixmap(0, 0, self._glow_pixmap)
        # Sprite
        px = (self.width() - self._pixmap.width()) // 2
        py = (self.height() - self._pixmap.height()) // 2
        p.drawPixmap(px, py, self._pixmap)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dismiss_timer.stop()
            self._bounce_timer.stop()
            self.clicked.emit(self._sprite_key)
            self.hide()
            self.deleteLater()


# ═══════════════════════════════════════════════════════════════════════════
# CollectibleCardDialog — shown when user picks up a collectible
# ═══════════════════════════════════════════════════════════════════════════

class CollectibleCardDialog(QWidget):
    """Frameless floating card showing a newly collected item."""

    accepted = pyqtSignal(dict)   # emits the collectible dict when user clicks Add
    dismissed = pyqtSignal()      # emits when user closes/dismisses the card

    def __init__(self, collectible: dict, appearance_mode: str | None = None, parent=None):
        super().__init__(parent)
        self._collectible = collectible
        self._appearance_mode = appearance_mode
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(320)

        self._build_ui()

        # Fade in
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._fade_in = QPropertyAnimation(self._opacity, b"opacity")
        self._fade_in.setDuration(500)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _build_ui(self):
        rarity = self._collectible.get("rarity", 1)
        rarity_color = _RARITY_COLORS.get(rarity, "#9E9E9E")
        sprite_key = self._collectible.get("sprite", "")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Card container
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(255, 248, 240, 240);
                border: 2px solid {rarity_color};
                border-radius: 14px;
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(8)
        card_layout.setContentsMargins(16, 14, 16, 14)

        # Close (X) button — top-right
        close_btn = QPushButton("✕")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #999;
                border: none;
                font-size: 14pt;
                font-weight: bold;
            }
            QPushButton:hover { color: #E53935; }
        """)
        close_btn.clicked.connect(self._on_dismiss)
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_row.addWidget(close_btn)
        close_row.setContentsMargins(0, 0, 0, 0)
        card_layout.addLayout(close_row)

        # Header
        header = QLabel(t("ui.collectible_new"))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet(f"font-size: 14pt; font-weight: bold; color: {rarity_color}; background: transparent;")
        card_layout.addWidget(header)

        # Sprite
        pix = get_sprite_pixmap(sprite_key, 64, glitch=(self._appearance_mode == "glitch"))
        img_label = QLabel()
        img_label.setPixmap(pix)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_label.setStyleSheet("background: transparent;")
        card_layout.addWidget(img_label)

        # Name
        name_label = QLabel(self._collectible.get("name", "???"))
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setStyleSheet("font-size: 12pt; font-weight: bold; color: #5A3E2B; background: transparent;")
        card_layout.addWidget(name_label)

        # Stars
        stars = QLabel(rarity_stars(rarity))
        stars.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stars.setStyleSheet("font-size: 14pt; background: transparent;")
        card_layout.addWidget(stars)

        # Rarity label
        rlabel = QLabel(_RARITY_LABELS.get(rarity, ""))
        rlabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rlabel.setStyleSheet(f"font-size: 9pt; color: {rarity_color}; font-weight: bold; background: transparent;")
        card_layout.addWidget(rlabel)

        # Description
        desc = QLabel(self._collectible.get("description", ""))
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("font-size: 10pt; color: #5A3E2B; font-style: italic; background: transparent; padding: 4px;")
        card_layout.addWidget(desc)

        # Button row: Add + Dismiss
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        add_btn = QPushButton(t("ui.collectible_add"))
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {rarity_color};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 10pt;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {QColor(rarity_color).lighter(120).name()};
            }}
        """)
        add_btn.clicked.connect(self._on_add)
        btn_row.addWidget(add_btn)

        dismiss_btn = QPushButton(t("ui.collectible_dismiss"))
        dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss_btn.setStyleSheet("""
            QPushButton {
                background-color: #E0E0E0;
                color: #666;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 10pt;
            }
            QPushButton:hover { background-color: #BDBDBD; }
        """)
        dismiss_btn.clicked.connect(self._on_dismiss)
        btn_row.addWidget(dismiss_btn)

        card_layout.addLayout(btn_row)

        layout.addWidget(card)
        self.adjustSize()

    def show_at(self, x: int, y: int):
        """Show the card at a position with fade-in."""
        from pal import get_screen_size
        try:
            sw, sh = get_screen_size()
            if x + self.width() > sw:
                x = sw - self.width() - 10
            if y + self.height() > sh:
                y = sh - self.height() - 10
            x = max(10, x)
            y = max(10, y)
        except Exception:
            pass
        self.move(x, y)
        self.show()
        wid = int(self.winId())
        remove_dwm_border(wid)
        if sys.platform == "darwin":
            set_topmost(wid)
        self._fade_in.start()

    def _on_add(self):
        self.accepted.emit(self._collectible)
        self.hide()
        self.deleteLater()

    def _on_dismiss(self):
        self.dismissed.emit()
        self.hide()
        self.deleteLater()

    def mousePressEvent(self, event):
        # Allow dragging or just ignore
        pass


# ═══════════════════════════════════════════════════════════════════════════
# CollectionPanel — full collection viewer (grid + detail)
# ═══════════════════════════════════════════════════════════════════════════

class _CollectionCard(QFrame):
    """Small card in the collection grid."""

    clicked = pyqtSignal(dict)

    def __init__(self, collectible: dict, parent=None):
        super().__init__(parent)
        self._data = collectible
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(110, 130)

        rarity = collectible.get("rarity", 1)
        rarity_color = _RARITY_COLORS.get(rarity, "#9E9E9E")
        is_new = self._is_recent(collectible)

        self.setStyleSheet(f"""
            _CollectionCard {{
                background-color: #FFFFFF;
                border: 2px solid {rarity_color};
                border-radius: 8px;
            }}
            _CollectionCard:hover {{
                background-color: #FFF0DC;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # NEW badge
        if is_new:
            badge = QLabel("NEW")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(f"font-size: 7pt; font-weight: bold; color: white; "
                                f"background: {rarity_color}; border-radius: 4px; padding: 1px 4px;")
            badge.setFixedHeight(14)
            layout.addWidget(badge)

        # Sprite
        pix = get_sprite_pixmap(collectible.get("sprite", ""), 48)
        img = QLabel()
        img.setPixmap(pix)
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img.setStyleSheet("background: transparent;")
        layout.addWidget(img)

        # Stars
        stars = QLabel(rarity_stars(rarity))
        stars.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stars.setStyleSheet("font-size: 9pt; background: transparent;")
        layout.addWidget(stars)

        # Name
        name = QLabel(collectible.get("name", "???"))
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 7pt; color: #5A3E2B; background: transparent;")
        name.setFixedHeight(24)
        layout.addWidget(name)

    @staticmethod
    def _is_recent(c: dict) -> bool:
        import datetime
        try:
            ts = datetime.datetime.fromisoformat(c["obtained_at"])
            return (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds() < 86400
        except Exception:
            return False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._data)
        super().mousePressEvent(event)


class CollectionPanel(QDialog):
    """Full collection viewer dialog with horizontal split layout."""

    deleted = pyqtSignal(str)  # emits collectible id when user deletes one

    def __init__(self, collection: list, parent=None):
        super().__init__(parent)
        self._collection = collection
        self._filter_rarity = 0  # 0 = all
        self._selected_id: str | None = None
        self.setWindowTitle(t("ui.collectible_panel_title"))
        self.setMinimumSize(780, 520)
        self.resize(820, 560)
        self.setStyleSheet("""
            QDialog {
                background-color: #FFF8F0;
                font-family: 'Segoe UI';
                color: #5A3E2B;
            }
            QLabel { color: #5A3E2B; }
            QComboBox {
                background-color: #FFFFFF;
                color: #5A3E2B;
                border: 1px solid #DDB892;
                border-radius: 4px;
                padding: 2px 6px;
            }
        """)
        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel(t("ui.collectible_panel_title"))
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        header.addWidget(title)

        self._count_label = QLabel(f"[{len(self._collection)} {t('ui.collectible_items')}]")
        self._count_label.setStyleSheet("font-size: 10pt; color: #999;")
        header.addWidget(self._count_label)
        header.addStretch()

        # Filter
        self._filter_combo = QComboBox()
        self._filter_combo.addItem(t("ui.collectible_filter_all"), 0)
        for r in range(1, 6):
            self._filter_combo.addItem(f"{rarity_stars(r)} {_RARITY_LABELS[r]}", r)
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        header.addWidget(QLabel(t("ui.collectible_filter")))
        header.addWidget(self._filter_combo)
        main_layout.addLayout(header)

        # Horizontal split: grid (left) + detail (right)
        split = QHBoxLayout()
        split.setSpacing(10)

        # Left: Scroll area with grid
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; }")
        split.addWidget(self._scroll, stretch=3)

        # Right: Detail panel
        self._detail_frame = QFrame()
        self._detail_frame.setFixedWidth(260)
        self._detail_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 248, 240, 240);
                border: 2px solid #DDB892;
                border-radius: 10px;
            }
        """)
        self._detail_frame.hide()
        self._detail_layout = QVBoxLayout(self._detail_frame)
        self._detail_layout.setContentsMargins(12, 12, 12, 12)
        self._detail_layout.setSpacing(6)
        split.addWidget(self._detail_frame)

        main_layout.addLayout(split)
        self._populate_grid()

    def _populate_grid(self):
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(8)
        grid.setContentsMargins(4, 4, 4, 4)

        items = self._collection
        if self._filter_rarity > 0:
            items = [c for c in items if c.get("rarity", 1) == self._filter_rarity]

        # Sort by rarity desc, then by date desc
        items = sorted(items, key=lambda c: (-c.get("rarity", 1), c.get("obtained_at", "")), reverse=False)

        cols = 4
        for i, c in enumerate(items):
            card = _CollectionCard(c)
            card.clicked.connect(self._show_detail)
            grid.addWidget(card, i // cols, i % cols)

        if not items:
            empty = QLabel(t("ui.collectible_empty"))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("font-size: 11pt; color: #999; padding: 40px;")
            grid.addWidget(empty, 0, 0, 1, cols)

        self._scroll.setWidget(container)

    def _on_filter_changed(self, index: int):
        self._filter_rarity = self._filter_combo.currentData()
        self._detail_frame.hide()
        self._selected_id = None
        self._populate_grid()

    def _show_detail(self, collectible: dict):
        self._selected_id = collectible.get("id")
        # Clear old detail
        while self._detail_layout.count():
            item = self._detail_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            else:
                # Clear sub-layouts
                sub = item.layout()
                if sub:
                    while sub.count():
                        sw = sub.takeAt(0).widget()
                        if sw:
                            sw.deleteLater()

        rarity = collectible.get("rarity", 1)
        rarity_color = _RARITY_COLORS.get(rarity, "#9E9E9E")

        # Sprite
        pix = get_sprite_pixmap(collectible.get("sprite", ""), 72)
        img = QLabel()
        img.setPixmap(pix)
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img.setStyleSheet("background: transparent;")
        self._detail_layout.addWidget(img)

        # Name
        name = QLabel(collectible.get("name", "???"))
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        name.setStyleSheet(f"font-size: 13pt; font-weight: bold; color: {rarity_color}; background: transparent;")
        self._detail_layout.addWidget(name)

        # Stars + rarity label
        stars = QLabel(rarity_stars(rarity) + f"  {_RARITY_LABELS.get(rarity, '')}")
        stars.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stars.setStyleSheet("font-size: 11pt; background: transparent;")
        self._detail_layout.addWidget(stars)

        # Description
        desc = QLabel(collectible.get("description", ""))
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("font-size: 10pt; color: #5A3E2B; font-style: italic; background: transparent; padding: 6px;")
        self._detail_layout.addWidget(desc)

        # Date
        date_str = collectible.get("obtained_at", "")[:10]
        if date_str:
            date_lbl = QLabel(date_str)
            date_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            date_lbl.setStyleSheet("font-size: 8pt; color: #999; background: transparent;")
            self._detail_layout.addWidget(date_lbl)

        self._detail_layout.addStretch()

        # Delete button
        del_btn = QPushButton(t("ui.collectible_delete"))
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #E53935;
                border: 1px solid #E53935;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 9pt;
            }
            QPushButton:hover {
                background-color: #FFEBEE;
            }
        """)
        del_btn.clicked.connect(lambda: self._on_delete(collectible))
        self._detail_layout.addWidget(del_btn)

        self._detail_frame.show()

    def _on_delete(self, collectible: dict):
        """Ask for confirmation, then remove from collection."""
        from PyQt6.QtWidgets import QMessageBox
        cid = collectible.get("id", "")
        name = collectible.get("name", "???")
        msg = t("ui.collectible_delete_confirm").replace("{name}", name)
        reply = QMessageBox.question(
            self, t("ui.collectible_delete"),
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._collection[:] = [c for c in self._collection if c.get("id") != cid]
            self.deleted.emit(cid)
            self._detail_frame.hide()
            self._selected_id = None
            self._count_label.setText(f"[{len(self._collection)} {t('ui.collectible_items')}]")
            self._populate_grid()
