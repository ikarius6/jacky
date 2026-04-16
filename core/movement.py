import logging
import random
from typing import Optional, Tuple, List

from pal import get_work_area, get_taskbar_rect, WindowInfo

log = logging.getLogger("movement")

# Default fallback bounds
_DEFAULT_BOUNDS = (0, 0, 1920, 1080)


class MovementEngine:
    """Handles Jacky's autonomous walking, platform detection, and screen bounds."""

    def __init__(self, sprite_size: int = 128, speed: int = 3):
        self._sprite_size = sprite_size
        self._speed = speed
        self._x: int = 0
        self._y: int = 0
        self._target_x: Optional[int] = None
        self._target_y: Optional[int] = None
        self._direction: int = 1  # 1=right, -1=left
        self._platforms: List[Tuple[int, int, int, int]] = []  # (left, top, right, bottom)
        self._ground_y: int = 0
        self._is_on_platform: bool = False
        self._current_platform: Optional[Tuple[int, int, int, int]] = None
        self._bounds: Optional[Tuple[int, int, int, int]] = None  # (left, top, right, bottom)
        self._current_screen_bounds: Optional[Tuple[int, int, int, int]] = None
        self._screen_rects: List[Tuple[int, int, int, int]] = []  # per-monitor available geometries
        self._dpi_scale: float = 1.0
        self._just_dropped: bool = False
        self._speed_multiplier: float = 1.0
        self._gravity_enabled: bool = False
        self._refresh_ground()

    def update_bounds(self, left: int, top: int, right: int, bottom: int):
        """Set screen bounds from the host window (Qt coordinates)."""
        self._bounds = (left, top, right, bottom)
        self._refresh_ground()

    def update_current_screen(self, left: int, top: int, right: int, bottom: int):
        """Set the bounds of the screen the pet is currently on (for ground_y)."""
        self._current_screen_bounds = (left, top, right, bottom)
        self._ground_y = bottom - self._sprite_size

    def update_screen_rects(self, rects: List[Tuple[int, int, int, int]]):
        """Set the list of all available screen geometries (multi-monitor)."""
        self._screen_rects = rects

    def _get_bounds(self) -> Tuple[int, int, int, int]:
        """Return current screen bounds, preferring externally-set Qt bounds."""
        if self._bounds is not None:
            return self._bounds
        try:
            return get_work_area()
        except Exception:
            return _DEFAULT_BOUNDS

    def _refresh_ground(self):
        """Update the ground Y coordinate from the current screen bounds."""
        if self._current_screen_bounds is not None:
            self._ground_y = self._current_screen_bounds[3] - self._sprite_size
        else:
            bounds = self._get_bounds()
            self._ground_y = bounds[3] - self._sprite_size

    @property
    def x(self) -> int:
        return self._x

    @property
    def y(self) -> int:
        return self._y

    @property
    def direction(self) -> int:
        return self._direction

    @property
    def speed_multiplier(self) -> float:
        return self._speed_multiplier

    @speed_multiplier.setter
    def speed_multiplier(self, value: float):
        self._speed_multiplier = max(value, 1.0)

    @property
    def is_walking(self) -> bool:
        return self._target_x is not None

    def _clamp_to_screen(self):
        """Clamp position so the pet never leaves the visible screen area."""
        bounds = self._get_bounds()
        min_x = bounds[0]
        min_y = bounds[1]
        max_x = bounds[2] - self._sprite_size
        max_y = bounds[3] - self._sprite_size
        old_x, old_y = self._x, self._y
        self._x = max(min_x, min(self._x, max_x))
        self._y = max(min_y, min(self._y, max_y))
        if old_x != self._x or old_y != self._y:
            log.warning("CLAMP (%d,%d)->(%d,%d) bounds=(%d,%d,%d,%d)",
                        old_x, old_y, self._x, self._y, min_x, min_y, max_x, max_y)

    def set_dpi_scale(self, scale: float):
        """Set the DPI scale factor for converting win32 coords to Qt coords."""
        self._dpi_scale = max(scale, 1.0)

    def set_position(self, x: int, y: int):
        """Set Jacky's position directly (e.g., after drag)."""
        old_x, old_y = self._x, self._y
        self._x = x
        self._y = y
        self._clamp_to_screen()
        log.info("SET_POS (%d,%d) -> (%d,%d) [clamped: (%d,%d)]", old_x, old_y, x, y, self._x, self._y)

    def set_position_after_drop(self, x: int, y: int):
        """Set position after a drag-drop — enables window landing detection."""
        self._x = x
        self._y = y
        self._clamp_to_screen()
        self._just_dropped = True
        log.info("DROP_POS (%d,%d) clamped=(%d,%d) ground_y=%d airborne=%s", x, y, self._x, self._y, self._ground_y, self.is_airborne)

    def update_platforms(self, windows: List[WindowInfo]):
        """Update the list of platforms Jacky can walk on (window top edges)."""
        self._platforms = []
        s = self._dpi_scale
        for w in windows:
            if w.is_minimized or w.is_maximized:
                continue
            # Store full window rect scaled to Qt logical coordinates
            self._platforms.append((
                int(w.left / s),
                int(w.top / s),
                int(w.right / s),
                int(w.bottom / s),
            ))

    def set_gravity(self, enabled: bool):
        """Enable or disable gravity mode."""
        self._gravity_enabled = enabled

    @property
    def gravity_enabled(self) -> bool:
        return self._gravity_enabled

    def pick_random_target(self):
        """Choose a random target position to walk toward.

        With gravity enabled the pet walks on the ground or on window-top
        platforms.  Without gravity it roams freely across all screens.
        """
        if self._gravity_enabled:
            self._pick_random_target_gravity()
        else:
            self._pick_random_target_free()

    def _pick_random_target_free(self):
        """Free-roam target selection (gravity off)."""
        if self._screen_rects:
            rect = random.choice(self._screen_rects)
            min_x, min_y = rect[0], rect[1]
            max_x = rect[2] - self._sprite_size
            max_y = rect[3] - self._sprite_size
        else:
            bounds = self._get_bounds()
            min_x, min_y = bounds[0], bounds[1]
            max_x = bounds[2] - self._sprite_size
            max_y = bounds[3] - self._sprite_size

        self._target_x = random.randint(min_x, max(min_x, max_x))
        self._target_y = random.randint(min_y, max(min_y, max_y))
        self._direction = 1 if self._target_x > self._x else -1
        log.info("TARGET free (%d,%d)->(%d,%d) screens=%d",
                 self._x, self._y, self._target_x, self._target_y, len(self._screen_rects))

    def _pick_random_target_gravity(self):
        """Ground/platform target selection (gravity on)."""
        bounds = self._get_bounds()
        min_x = bounds[0]
        max_x = bounds[2] - self._sprite_size

        # Occasionally pick a platform to walk onto
        pet_feet_y = self._y + self._sprite_size
        max_climb = self._sprite_size
        walkable = [
            p for p in self._platforms
            if p[1] >= self._sprite_size
            and abs(pet_feet_y - p[1]) <= max_climb
        ]
        if walkable and random.random() < 0.3:
            plat = random.choice(walkable)
            plat_min_x = max(plat[0], min_x)
            plat_max_x = min(plat[2] - self._sprite_size, max_x)
            if plat_min_x < plat_max_x:
                self._target_x = random.randint(plat_min_x, plat_max_x)
                self._target_y = plat[1] - self._sprite_size
                self._direction = 1 if self._target_x > self._x else -1
                log.info("TARGET platform (%d,%d)->(%d,%d) bounds=%s plat=%s",
                         self._x, self._y, self._target_x, self._target_y, bounds, plat)
                return

        # Walk on ground
        self._target_x = random.randint(min_x, max(min_x, max_x))
        self._target_y = self._ground_y
        self._direction = 1 if self._target_x > self._x else -1
        log.info("TARGET ground (%d,%d)->(%d,%d) bounds=%s",
                 self._x, self._y, self._target_x, self._target_y, bounds)

    def stop(self):
        """Stop walking."""
        self._target_x = None
        self._target_y = None

    def tick(self) -> bool:
        """
        Advance one movement step toward the target.
        Returns True if still moving, False if arrived or no target.
        """
        if self._target_x is None:
            return False

        effective_speed = int(self._speed * self._speed_multiplier)
        prev_x, prev_y = self._x, self._y

        dx = self._target_x - self._x
        dy = (self._target_y if self._target_y is not None else self._ground_y) - self._y

        # Move X
        if abs(dx) <= effective_speed:
            self._x = self._target_x
        else:
            self._x += effective_speed if dx > 0 else -effective_speed

        # Move Y (vertical transitions between platforms/ground)
        if abs(dy) <= effective_speed:
            self._y = self._target_y if self._target_y is not None else self._ground_y
        else:
            self._y += effective_speed if dy > 0 else -effective_speed

        self._clamp_to_screen()

        # Check arrival
        if self._x == self._target_x and self._y == (self._target_y or self._ground_y):
            self._target_x = None
            self._target_y = None
            return False

        # Check stuck: no progress after clamp means target is unreachable
        if self._x == prev_x and self._y == prev_y:
            log.info("STUCK at (%d,%d) target=(%s,%s) — treating as arrived",
                     self._x, self._y, self._target_x, self._target_y)
            self._target_x = None
            self._target_y = None
            return False

        return True

    @property
    def is_airborne(self) -> bool:
        """Return True if the pet is above ground and not resting on a platform.

        Always returns False when gravity is disabled.
        """
        if not self._gravity_enabled:
            return False
        self._refresh_ground()
        if self._y >= self._ground_y:
            return False
        pet_bottom = self._y + self._sprite_size
        pet_center_x = self._x + self._sprite_size // 2
        for plat in self._platforms:
            if plat[1] < self._sprite_size:
                continue  # platform too close to screen top
            if plat[0] <= pet_center_x <= plat[2]:
                if abs(pet_bottom - plat[1]) < 15:
                    return False
        return True

    def apply_gravity(self):
        """If not on a platform and not walking, apply gravity to ground.

        No-op when gravity is disabled.
        """
        if not self._gravity_enabled:
            return
        if self._target_x is not None:
            return  # Already moving

        self._refresh_ground()
        pet_bottom = self._y + self._sprite_size
        pet_center_x = self._x + self._sprite_size // 2

        # 1. Check if already resting on a platform surface
        for plat in self._platforms:
            if plat[1] < self._sprite_size:
                continue  # platform too close to screen top
            if plat[0] <= pet_center_x <= plat[2]:
                plat_top = plat[1]
                if abs(pet_bottom - plat_top) < 15:
                    self._y = plat_top - self._sprite_size
                    self._just_dropped = False
                    self._clamp_to_screen()
                    return

        # 2. After drag-drop: if pet overlaps a window body, slide up to its top
        if self._just_dropped:
            for plat in self._platforms:
                plat_left, plat_top, plat_right, plat_bottom = plat
                if plat_top < self._sprite_size:
                    continue  # platform too close to screen top
                if plat_left <= pet_center_x <= plat_right:
                    # Only slide up if feet are near the window top (within sprite_size)
                    overlap = pet_bottom - plat_top
                    if 0 < overlap <= self._sprite_size:
                        target_y = plat_top - self._sprite_size
                        if self._y > target_y:
                            self._y = max(self._y - self._speed * 3, target_y)
                        if abs(self._y - target_y) < 2:
                            self._y = target_y
                            self._just_dropped = False
                        self._clamp_to_screen()
                        return
            # Not inside any window — clear flag, continue with normal fall
            self._just_dropped = False

        # 3. Fall toward ground, checking for window tops in the fall path
        if self._y < self._ground_y:
            fall_step = self._speed * 2
            next_bottom = pet_bottom + fall_step

            best_land_y = None
            for plat in self._platforms:
                if plat[1] < self._sprite_size:
                    continue  # platform too close to screen top
                if plat[0] <= pet_center_x <= plat[2]:
                    plat_top = plat[1]
                    if pet_bottom <= plat_top <= next_bottom:
                        land_y = plat_top - self._sprite_size
                        if best_land_y is None or land_y < best_land_y:
                            best_land_y = land_y

            if best_land_y is not None:
                self._y = best_land_y
                self._just_dropped = False
            else:
                self._y = min(self._y + fall_step, self._ground_y)

        self._clamp_to_screen()
