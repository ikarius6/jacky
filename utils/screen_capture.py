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
