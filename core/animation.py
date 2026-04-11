import os
from typing import Dict, List, Optional

from PyQt6.QtGui import QPixmap, QTransform
from PyQt6.QtCore import Qt, QTimer


class AnimationController:
    """Loads and cycles sprite frames by state name.

    Supports two sprite layouts:
      - "flat": single directory with {state}_{index}.png files
      - "sequence_dirs": subdirectories per animation, mapped via state_map
    """

    def __init__(self, sprites_dir: str, sprite_size: int = 128, fps: int = 6,
                 layout: str = "flat", state_map: Dict[str, str] | None = None):
        self._sprites_dir = sprites_dir
        self._sprite_size = sprite_size
        self._fps = fps
        self._layout = layout
        self._state_map = state_map or {}
        self._frames: Dict[str, List[QPixmap]] = {}
        self._current_state: str = "idle"
        self._frame_index: int = 0
        # Runtime facing direction — True means the pet is looking left.
        self._facing_left: bool = False
        self._load_all_sprites()

    def _load_all_sprites(self):
        """Load sprites based on the layout type."""
        if not os.path.isdir(self._sprites_dir):
            return
        if self._layout == "sequence_dirs":
            self._load_sequence_dirs()
        else:
            self._load_flat()

    def _load_flat(self):
        """Scan a flat directory and load frames grouped by state prefix."""
        files = sorted(os.listdir(self._sprites_dir))
        for fname in files:
            if not fname.endswith(".png"):
                continue
            # e.g. "idle_0.png" -> state="idle", index=0
            base = fname[:-4]  # strip .png
            parts = base.rsplit("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                state_name = parts[0]
            else:
                state_name = base
            self._load_frame(state_name, os.path.join(self._sprites_dir, fname), flip=False)

    def _load_sequence_dirs(self):
        """Load from subdirectories, using state_map to assign animation names."""
        # Build reverse map: directory name -> list of state_names
        dir_to_states: Dict[str, List[str]] = {}
        for anim_name, dir_name in self._state_map.items():
            dir_to_states.setdefault(dir_name, []).append(anim_name)

        for dir_name, state_names in dir_to_states.items():
            dir_path = os.path.join(self._sprites_dir, dir_name)
            if not os.path.isdir(dir_path):
                continue
            files = sorted(os.listdir(dir_path))
            png_files = [f for f in files if f.lower().endswith(".png")]
            for anim_name in state_names:
                for fname in png_files:
                    self._load_frame(anim_name, os.path.join(dir_path, fname))

    def _load_frame(self, state_name: str, path: str):
        """Load a single frame, scale it, and store it."""
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        pixmap = pixmap.scaled(
            self._sprite_size, self._sprite_size,
            aspectRatioMode=Qt.AspectRatioMode.KeepAspectRatio,
            transformMode=Qt.TransformationMode.SmoothTransformation,
        )
        if state_name not in self._frames:
            self._frames[state_name] = []
        self._frames[state_name].append(pixmap)

    def dispose(self):
        """Explicitly release all cached pixmaps to free memory immediately."""
        for frames in self._frames.values():
            frames.clear()
        self._frames.clear()

    @property
    def available_states(self) -> List[str]:
        return list(self._frames.keys())

    @property
    def current_state(self) -> str:
        return self._current_state

    @property
    def sprite_size(self) -> int:
        return self._sprite_size

    def set_state(self, state_name: str):
        """Switch to a new animation state. Resets frame index."""
        if state_name == self._current_state:
            return
        if state_name in self._frames:
            self._current_state = state_name
            self._frame_index = 0

    def set_facing(self, facing_left: bool) -> None:
        """Update the direction the pet is facing.

        When ``facing_left`` is True, all frames returned by ``tick()`` and
        ``current_frame()`` are horizontally mirrored on the fly.
        """
        self._facing_left = facing_left

    def _maybe_flip(self, pixmap: QPixmap) -> QPixmap:
        """Return a horizontally flipped copy of *pixmap* if the pet faces left."""
        if self._facing_left:
            return pixmap.transformed(QTransform().scale(-1, 1))
        return pixmap

    def tick(self) -> Optional[QPixmap]:
        """Advance to next frame and return current pixmap."""
        frames = self._frames.get(self._current_state)
        if not frames:
            return None
        self._frame_index = (self._frame_index + 1) % len(frames)
        return self._maybe_flip(frames[self._frame_index])

    def current_frame(self) -> Optional[QPixmap]:
        """Return current frame without advancing."""
        frames = self._frames.get(self._current_state)
        if not frames:
            return None
        return self._maybe_flip(frames[self._frame_index % len(frames)])

    @property
    def frame_interval_ms(self) -> int:
        """Milliseconds between frames based on FPS."""
        return max(1, 1000 // self._fps)
