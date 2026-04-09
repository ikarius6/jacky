"""Debug image helpers for screen-interaction diagnostics.

Saves intermediate screenshots (grid overlays, crops, crosshair markers)
to ``debug_screens/`` so the developer can visually inspect each phase.
"""

import base64
import logging
import os

from PyQt6.QtGui import QImage, QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt
from utils.paths import get_config_dir

log = logging.getLogger("screen_interaction")

# Module-level gate: when False every save/mark function is a no-op.
_enabled = False

DEBUG_DIR = os.path.join(get_config_dir(), "debug_screens")


def set_enabled(flag: bool):
    """Enable or disable debug screen recording at runtime."""
    global _enabled
    _enabled = flag


def save_b64(b64_data: str, filename: str):
    """Save a base64-encoded PNG to *DEBUG_DIR*."""
    if not _enabled:
        return
    os.makedirs(DEBUG_DIR, exist_ok=True)
    path = os.path.join(DEBUG_DIR, filename)
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64_data))
    log.debug("DBG saved %s", filename)


def save_qimage(qimage, filename: str):
    """Save a QImage as PNG to *DEBUG_DIR*."""
    if not _enabled:
        return
    os.makedirs(DEBUG_DIR, exist_ok=True)
    path = os.path.join(DEBUG_DIR, filename)
    qimage.save(path, "PNG")
    log.debug("DBG saved %s", filename)


def mark_point(src_filename: str, dst_filename: str,
               x: float, y: float, label: str):
    """Load *src*, draw crosshair + label at (x, y), save as *dst*."""
    if not _enabled:
        return
    src = os.path.join(DEBUG_DIR, src_filename)
    dst = os.path.join(DEBUG_DIR, dst_filename)
    img = QImage(src)
    if img.isNull():
        return

    ix, iy = int(x), int(y)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Green crosshair
    pen = QPen(QColor(0, 255, 0), 3)
    painter.setPen(pen)
    painter.drawLine(ix - 30, iy, ix + 30, iy)
    painter.drawLine(ix, iy - 30, ix, iy + 30)

    # Red circle
    pen = QPen(QColor(255, 0, 0), 2)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(ix - 18, iy - 18, 36, 36)

    # Yellow label with dark background
    font = QFont("Arial", 14, QFont.Weight.Bold)
    painter.setFont(font)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 180))
    painter.drawRect(ix + 22, iy - 22, len(label) * 9 + 10, 24)
    painter.setPen(QColor(255, 255, 0))
    painter.drawText(ix + 27, iy - 3, label)

    painter.end()
    img.save(dst, "PNG")
    log.debug("DBG marked %s -> %s at (%d,%d)", src_filename, dst_filename, ix, iy)


def mark_cell(src_filename: str, dst_filename: str,
              cell_num: int, cols: int, rows: int,
              cell_w: float, cell_h: float):
    """Highlight a grid cell on a saved debug image."""
    if not _enabled:
        return
    src = os.path.join(DEBUG_DIR, src_filename)
    dst = os.path.join(DEBUG_DIR, dst_filename)
    img = QImage(src)
    if img.isNull():
        return

    col = (cell_num - 1) % cols
    row = (cell_num - 1) // cols
    rx, ry = int(col * cell_w), int(row * cell_h)
    rw, rh = int(cell_w), int(cell_h)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(0, 255, 0, 50))
    pen = QPen(QColor(0, 255, 0), 4)
    painter.setPen(pen)
    painter.drawRect(rx, ry, rw, rh)

    font = QFont("Arial", 18, QFont.Weight.Bold)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 0))
    painter.drawText(rx + 10, ry + 30, f"SELECTED: Cell {cell_num}")

    painter.end()
    img.save(dst, "PNG")
    log.debug("DBG cell %d highlighted %s", cell_num, dst_filename)
