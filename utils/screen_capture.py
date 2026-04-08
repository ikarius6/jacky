import base64
import io
import logging
from typing import Tuple

import mss
import mss.tools

log = logging.getLogger("screen_capture")

# Default vision area size in physical pixels
VISION_SIZE = 1024


def _get_virtual_desktop(sct: mss.mss) -> Tuple[int, int, int, int]:
    """Return (left, top, right, bottom) of the full virtual desktop."""
    # mss.monitors[0] is always the "all-in-one" virtual monitor
    mon = sct.monitors[0]
    return (mon["left"], mon["top"],
            mon["left"] + mon["width"], mon["top"] + mon["height"])


def capture_vision_area(
    pet_center_x: int,
    pet_center_y: int,
    size: int = VISION_SIZE,
    dpi_scale: float = 1.0,
) -> str:
    """Capture a square area centred on the pet and return it as a base64 PNG.

    Parameters
    ----------
    pet_center_x, pet_center_y : int
        Centre of the pet in **Qt logical** coordinates.
    size : int
        Side length of the capture square in physical pixels.
    dpi_scale : float
        The device-pixel-ratio so we can convert logical → physical coords.

    Returns
    -------
    str
        Base64-encoded PNG image data (no ``data:`` prefix).
    """
    # Convert logical (Qt) coordinates to physical (screen) pixels
    px = int(pet_center_x * dpi_scale)
    py = int(pet_center_y * dpi_scale)

    with mss.mss() as sct:
        vd_left, vd_top, vd_right, vd_bottom = _get_virtual_desktop(sct)
        vd_w = vd_right - vd_left
        vd_h = vd_bottom - vd_top

        # Clamp size to virtual desktop dimensions
        w = min(size, vd_w)
        h = min(size, vd_h)

        # Ideal bounding box centred on pet
        left = px - w // 2
        top = py - h // 2
        right = left + w
        bottom = top + h

        # Clamp to virtual desktop edges (shift, don't shrink)
        if left < vd_left:
            left = vd_left
            right = left + w
        if top < vd_top:
            top = vd_top
            bottom = top + h
        if right > vd_right:
            right = vd_right
            left = right - w
        if bottom > vd_bottom:
            bottom = vd_bottom
            top = bottom - h

        region = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        log.debug("Capturing vision area %s (pet phys=%d,%d dpi=%.2f)", region, px, py, dpi_scale)

        sct_img = sct.grab(region)
        png_bytes = mss.tools.to_png(sct_img.rgb, sct_img.size)

    return base64.b64encode(png_bytes).decode("ascii")


def capture_full_screen(target_width: int = 2048) -> Tuple[str, Tuple[int, int], float]:
    """Capture the full virtual desktop, resize to *target_width* keeping aspect ratio.

    Returns
    -------
    tuple[str, tuple[int, int], float]
        ``(base64_png, (original_width, original_height), scale_factor)``
        where ``scale_factor = original_width / resized_width`` so that
        coordinates obtained from the resized image can be mapped back to
        physical screen coordinates by multiplying by *scale_factor*.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage

    with mss.mss() as sct:
        mon = sct.monitors[0]  # full virtual desktop
        sct_img = sct.grab(mon)
        # Use actual captured dimensions (safe with DPI scaling)
        orig_w = sct_img.width
        orig_h = sct_img.height
        raw_bytes = bytes(sct_img.rgb)

    # mss .rgb converts native BGRA to RGB — QImage Format_RGB888 matches directly
    qimg = QImage(raw_bytes, orig_w, orig_h, orig_w * 3, QImage.Format.Format_RGB888)

    # Resize keeping aspect ratio
    resized = qimg.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
    resized_w = resized.width()
    scale_factor = orig_w / resized_w

    # Convert to PNG bytes via QBuffer

    from PyQt6.QtCore import QBuffer, QIODevice
    qbuf = QBuffer()
    qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
    resized.save(qbuf, "PNG")
    png_bytes = bytes(qbuf.data())
    qbuf.close()

    log.debug("capture_full_screen: orig=%dx%d resized=%dx%d scale=%.2f png_size=%d",
              orig_w, orig_h, resized_w, resized.height(), scale_factor, len(png_bytes))

    return base64.b64encode(png_bytes).decode("ascii"), (orig_w, orig_h), scale_factor


def draw_subgrid(qimage, cols: int = 3, rows: int = 3):
    """Draw a numbered grid overlay on a QImage (for sub-cell classification).

    Returns ``(gridded_copy, cell_w, cell_h)`` — the copy has grid lines and
    numbered badges exactly like the full-screen version.  The original is
    not modified.

    Numbers are placed in the **center** of each cell so the LLM can
    unambiguously associate a number with its cell.
    """
    from PyQt6.QtCore import Qt, QRect
    from PyQt6.QtGui import QPainter, QColor, QPen, QFont

    gridded = qimage.copy()
    w = gridded.width()
    h = gridded.height()
    cell_w = w / cols
    cell_h = h / rows

    painter = QPainter(gridded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Grid lines — semi-transparent green, 1 px
    pen = QPen(QColor(0, 200, 0, 180), 1)
    painter.setPen(pen)
    for c in range(1, cols):
        x = int(c * cell_w)
        painter.drawLine(x, 0, x, h)
    for r in range(1, rows):
        y = int(r * cell_h)
        painter.drawLine(0, y, w, y)

    # Cell numbers — badges centered in each cell
    total = cols * rows
    font_size = max(9, 14 if total <= 9 else (12 if total <= 24 else 10))
    radius = max(9, 14 if total <= 9 else (12 if total <= 24 else 10))
    font = QFont("Arial", font_size, QFont.Weight.Bold)
    painter.setFont(font)
    for r in range(rows):
        for c in range(cols):
            num = r * cols + c + 1
            # Center of cell
            bx = int(c * cell_w + cell_w / 2)
            by = int(r * cell_h + cell_h / 2)
            # Semi-transparent background circle
            painter.setBrush(QColor(0, 0, 0, 140))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(bx - radius, by - radius, radius * 2, radius * 2)
            # Number text — white for contrast on dark badge
            painter.setPen(QColor(255, 255, 255, 230))
            rect = QRect(bx - radius, by - radius, radius * 2, radius * 2)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(num))

    painter.end()
    return gridded, cell_w, cell_h


def encode_qimage_png(qimage) -> str:
    """Encode a ``QImage`` as a base64 PNG string (no ``data:`` prefix)."""
    from PyQt6.QtCore import QBuffer, QIODevice

    qbuf = QBuffer()
    qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
    qimage.save(qbuf, "PNG")
    png_bytes = bytes(qbuf.data())
    qbuf.close()
    return base64.b64encode(png_bytes).decode("ascii")


def capture_full_screen_gridded(
    target_width: int = 2048,
    cols: int = 4,
    rows: int = 3,
):
    """Capture the full virtual desktop with a numbered grid overlay.

    Returns a tuple of five items:

    * *grid_b64* — base64 PNG **with** grid lines & numbers (sent to the LLM).
    * *clean_qimage* — resized ``QImage`` **without** the overlay (used to crop
      later for the second locate phase).
    * *(orig_w, orig_h)* — original physical screen resolution.
    * *scale_factor* — ``orig_w / resized_w`` for mapping back.
    * *(cell_w, cell_h)* — cell dimensions in *resized-image* pixels.
    """
    from PyQt6.QtCore import Qt, QBuffer, QIODevice, QRect
    from PyQt6.QtGui import QImage, QPainter, QFont, QColor, QPen

    with mss.mss() as sct:
        mon = sct.monitors[0]
        sct_img = sct.grab(mon)
        orig_w = sct_img.width
        orig_h = sct_img.height
        raw_bytes = bytes(sct_img.rgb)

    # mss .rgb converts native BGRA to RGB — QImage Format_RGB888 matches directly
    qimg = QImage(raw_bytes, orig_w, orig_h, orig_w * 3, QImage.Format.Format_RGB888)

    resized = qimg.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
    resized_w = resized.width()
    resized_h = resized.height()
    scale_factor = orig_w / resized_w

    # Keep a clean copy before drawing the grid
    clean = resized.copy()

    # --- Draw numbered grid overlay ---
    cell_w = resized_w / cols
    cell_h = resized_h / rows

    painter = QPainter(resized)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Grid lines — semi-transparent red, 1 px
    pen = QPen(QColor(255, 0, 0, 180), 1)
    painter.setPen(pen)
    for c in range(1, cols):
        x = int(c * cell_w)
        painter.drawLine(x, 0, x, resized_h)
    for r in range(1, rows):
        y = int(r * cell_h)
        painter.drawLine(0, y, resized_w, y)

    # Cell numbers — badges centered in each cell
    total = cols * rows
    font_size = max(10, 18 if total <= 12 else (14 if total <= 24 else 11))
    radius = max(10, 18 if total <= 12 else (14 if total <= 24 else 11))
    font = QFont("Arial", font_size, QFont.Weight.Bold)
    painter.setFont(font)
    for r in range(rows):
        for c in range(cols):
            num = r * cols + c + 1
            # Center of cell
            bx = int(c * cell_w + cell_w / 2)
            by = int(r * cell_h + cell_h / 2)
            # Semi-transparent dark background circle
            painter.setBrush(QColor(0, 0, 0, 150))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(bx - radius, by - radius, radius * 2, radius * 2)
            # Number text — white for contrast on dark badge
            painter.setPen(QColor(255, 255, 255, 240))
            rect = QRect(bx - radius, by - radius, radius * 2, radius * 2)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(num))

    painter.end()

    # Encode grid image as PNG
    qbuf = QBuffer()
    qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
    resized.save(qbuf, "PNG")
    grid_png = bytes(qbuf.data())
    qbuf.close()

    log.debug(
        "capture_full_screen_gridded: orig=%dx%d resized=%dx%d scale=%.2f grid=%dx%d png=%d",
        orig_w, orig_h, resized_w, resized_h, scale_factor, cols, rows, len(grid_png),
    )

    return (
        base64.b64encode(grid_png).decode("ascii"),
        clean,
        (orig_w, orig_h),
        scale_factor,
        (cell_w, cell_h),
    )
