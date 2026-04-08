"""Data model for an in-progress screen interaction task."""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class ScreenInteractionTask:
    """Data class for an in-progress screen interaction task."""
    action_type: str       # "navigate" | "click" | "close" | "minimize"
    target_desc: str       # "el botón de Chrome", "cerrar", etc.
    state: str = "pending" # "pending"|"locating"|"moving"|"refining"|"executing"|"done"|"failed"|"cancelled"
    target_coords: Optional[Tuple[int, int]] = None  # (x, y) in Qt logical coords
    confidence: int = 0    # 0-100 from LLM
    scale_factor: float = 1.0
    original_size: Tuple[int, int] = (1920, 1080)
