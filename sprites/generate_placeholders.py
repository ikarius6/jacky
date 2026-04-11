"""
Generate placeholder chibi sprites for Jacky using QPainter.
Run once to create PNG files in sprites/placeholder/.
"""
import os
import sys

# Add project root to path so we can run standalone
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPainter, QColor, QPixmap, QBrush, QPen, QFont, QPainterPath
from PyQt6.QtCore import Qt, QRectF, QPointF

from utils.paths import get_data_dir

SIZE = 128
OUT_DIR = os.path.join(get_data_dir(), "sprites", "placeholder")


# Color palette
SKIN = QColor(255, 220, 185)
HAIR = QColor(80, 50, 30)
EYE = QColor(40, 40, 40)
MOUTH = QColor(200, 80, 80)
BLUSH = QColor(255, 180, 180, 120)
BODY_COLOR = QColor(100, 160, 255)
SHOE_COLOR = QColor(60, 60, 60)
OUTLINE = QColor(60, 40, 30)


def _draw_chibi_base(p: QPainter, eye_state="open", mouth_state="closed",
                     leg_offset=0, arm_offset=0, blush=False):
    """Draw the base chibi character."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(OUTLINE, 2)
    p.setPen(pen)

    cx = SIZE // 2
    head_y = 20
    head_r = 30  # head radius
    body_top = head_y + head_r + 2
    body_h = 30
    leg_len = 18

    # Hair (behind head)
    p.setBrush(QBrush(HAIR))
    p.drawEllipse(QPointF(cx, head_y - 2), head_r + 6, head_r + 6)

    # Head
    p.setBrush(QBrush(SKIN))
    p.drawEllipse(QPointF(cx, head_y), head_r, head_r)

    # Hair bangs (on top)
    p.setBrush(QBrush(HAIR))
    bang_path = QPainterPath()
    bang_path.moveTo(cx - head_r - 2, head_y - 5)
    bang_path.quadTo(cx - 10, head_y - head_r - 8, cx, head_y - head_r + 2)
    bang_path.quadTo(cx + 10, head_y - head_r - 8, cx + head_r + 2, head_y - 5)
    bang_path.quadTo(cx + head_r - 5, head_y - 2, cx + 5, head_y - 8)
    bang_path.quadTo(cx - 5, head_y - 2, cx - head_r + 5, head_y - 8)
    bang_path.closeSubpath()
    p.drawPath(bang_path)

    # Eyes
    p.setPen(QPen(EYE, 2))
    p.setBrush(QBrush(EYE))
    eye_y = head_y + 2
    if eye_state == "open":
        p.drawEllipse(QPointF(cx - 10, eye_y), 4, 5)
        p.drawEllipse(QPointF(cx + 10, eye_y), 4, 5)
        # Eye highlights
        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx - 8, eye_y - 2), 2, 2)
        p.drawEllipse(QPointF(cx + 12, eye_y - 2), 2, 2)
    elif eye_state == "closed":
        p.setPen(QPen(EYE, 2.5))
        p.drawArc(int(cx - 14), int(eye_y - 3), 8, 6, 0, 180 * 16)
        p.drawArc(int(cx + 6), int(eye_y - 3), 8, 6, 0, 180 * 16)
    elif eye_state == "blink":
        p.setPen(QPen(EYE, 2))
        p.drawLine(int(cx - 14), int(eye_y), int(cx - 6), int(eye_y))
        p.drawLine(int(cx + 6), int(eye_y), int(cx + 14), int(eye_y))
    elif eye_state == "surprised":
        p.drawEllipse(QPointF(cx - 10, eye_y), 5, 6)
        p.drawEllipse(QPointF(cx + 10, eye_y), 5, 6)
        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx - 8, eye_y - 2), 2.5, 2.5)
        p.drawEllipse(QPointF(cx + 12, eye_y - 2), 2.5, 2.5)

    # Blush
    if blush:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(BLUSH))
        p.drawEllipse(QPointF(cx - 18, eye_y + 8), 7, 4)
        p.drawEllipse(QPointF(cx + 18, eye_y + 8), 7, 4)

    # Mouth
    p.setPen(QPen(MOUTH, 2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    mouth_y = head_y + 14
    if mouth_state == "closed":
        p.drawLine(int(cx - 4), int(mouth_y), int(cx + 4), int(mouth_y))
    elif mouth_state == "open":
        p.setBrush(QBrush(MOUTH))
        p.drawEllipse(QPointF(cx, mouth_y), 5, 4)
    elif mouth_state == "smile":
        p.drawArc(int(cx - 6), int(mouth_y - 4), 12, 8, 0, -180 * 16)

    # Body
    p.setPen(QPen(OUTLINE, 2))
    p.setBrush(QBrush(BODY_COLOR))
    body_rect = QRectF(cx - 16, body_top, 32, body_h)
    p.drawRoundedRect(body_rect, 6, 6)

    # Arms
    p.setPen(QPen(OUTLINE, 2.5))
    p.setBrush(QBrush(SKIN))
    # Left arm
    la_x = cx - 16 + arm_offset
    p.drawLine(int(cx - 16), int(body_top + 5), int(la_x - 10), int(body_top + body_h - 5))
    p.drawEllipse(QPointF(la_x - 10, body_top + body_h - 5), 4, 4)
    # Right arm
    ra_x = cx + 16 - arm_offset
    p.drawLine(int(cx + 16), int(body_top + 5), int(ra_x + 10), int(body_top + body_h - 5))
    p.drawEllipse(QPointF(ra_x + 10, body_top + body_h - 5), 4, 4)

    # Legs
    leg_top = body_top + body_h
    p.setPen(QPen(OUTLINE, 2.5))
    # Left leg
    p.drawLine(int(cx - 8), int(leg_top), int(cx - 8 + leg_offset), int(leg_top + leg_len))
    # Right leg
    p.drawLine(int(cx + 8), int(leg_top), int(cx + 8 - leg_offset), int(leg_top + leg_len))
    # Shoes
    p.setBrush(QBrush(SHOE_COLOR))
    p.drawEllipse(QPointF(cx - 8 + leg_offset, leg_top + leg_len), 6, 4)
    p.drawEllipse(QPointF(cx + 8 - leg_offset, leg_top + leg_len), 6, 4)


def _create_frame(draw_func, filename):
    """Create a single sprite frame."""
    pixmap = QPixmap(SIZE, SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    draw_func(p)
    p.end()
    path = os.path.join(OUT_DIR, filename)
    pixmap.save(path, "PNG")
    print(f"  Created: {filename}")


def generate():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Generating placeholder sprites...")

    # IDLE frames (4): open, open, blink, open
    eye_states = ["open", "open", "blink", "open"]
    for i, es in enumerate(eye_states):
        _create_frame(
            lambda p, es=es: _draw_chibi_base(p, eye_state=es, mouth_state="closed"),
            f"idle_{i}.png"
        )

    # WALK frames (4): alternating legs
    leg_offsets = [0, 4, 0, -4]
    for i, lo in enumerate(leg_offsets):
        _create_frame(
            lambda p, lo=lo: _draw_chibi_base(p, eye_state="open", mouth_state="closed", leg_offset=lo),
            f"walk_{i}.png"
        )

    # TALK frames (2): mouth open/closed
    _create_frame(
        lambda p: _draw_chibi_base(p, eye_state="open", mouth_state="open"),
        "talk_0.png"
    )
    _create_frame(
        lambda p: _draw_chibi_base(p, eye_state="open", mouth_state="closed"),
        "talk_1.png"
    )

    # HAPPY frames (2): closed eyes, smile, blush
    _create_frame(
        lambda p: _draw_chibi_base(p, eye_state="closed", mouth_state="smile", blush=True),
        "happy_0.png"
    )
    _create_frame(
        lambda p: _draw_chibi_base(p, eye_state="closed", mouth_state="smile", blush=True, arm_offset=3),
        "happy_1.png"
    )

    # DRAG frame (1): surprised
    _create_frame(
        lambda p: _draw_chibi_base(p, eye_state="surprised", mouth_state="open"),
        "drag_0.png"
    )

    print(f"Done! Sprites saved to: {OUT_DIR}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    generate()
    sys.exit(0)
