from enum import Enum, auto
from typing import Optional, Callable, List


class PetState(Enum):
    IDLE = auto()
    WALKING = auto()
    TALKING = auto()
    DRAGGED = auto()
    INTERACTING = auto()
    PEEKING = auto()
    HAPPY = auto()
    EATING = auto()
    RUNNING = auto()
    JUMPING = auto()
    FALLING = auto()
    HURT = auto()
    SHOOTING = auto()
    SLASHING = auto()
    THROWING = auto()
    SLIDING = auto()


# Maps pet states to animation state names (sprite prefixes)
STATE_ANIMATION_MAP = {
    PetState.IDLE: "idle",
    PetState.WALKING: "walk_right",  # overridden by direction
    PetState.TALKING: "talk",
    PetState.DRAGGED: "drag",
    PetState.INTERACTING: "kick",
    PetState.PEEKING: "idle",
    PetState.HAPPY: "happy",
    PetState.EATING: "happy",
    PetState.RUNNING: "run_right",  # overridden by direction
    PetState.JUMPING: "jump_loop",
    PetState.FALLING: "falling",
    PetState.HURT: "hurt",
    PetState.SHOOTING: "shooting",
    PetState.SLASHING: "slashing",
    PetState.THROWING: "throwing",
    PetState.SLIDING: "sliding",
}


class Pet:
    """Pet state machine — manages Jacky's current state and transitions."""

    def __init__(self, name: str = "Jacky"):
        self.name = name
        self._state = PetState.IDLE
        self._previous_state = PetState.IDLE
        self._direction = 1  # 1 = right, -1 = left
        self._on_state_change: List[Callable[[PetState, PetState], None]] = []

    @property
    def state(self) -> PetState:
        return self._state

    @property
    def previous_state(self) -> PetState:
        return self._previous_state

    @property
    def direction(self) -> int:
        return self._direction

    @direction.setter
    def direction(self, value: int):
        self._direction = 1 if value >= 0 else -1

    def on_state_change(self, callback: Callable[[PetState, PetState], None]):
        """Register a callback for state changes: callback(old_state, new_state)."""
        self._on_state_change.append(callback)

    def set_state(self, new_state: PetState):
        """Transition to a new state."""
        if new_state == self._state:
            return
        old = self._state
        self._previous_state = old
        self._state = new_state
        for cb in self._on_state_change:
            cb(old, new_state)

    def get_animation_name(self) -> str:
        """Return the animation state name for the current pet state."""
        if self._state == PetState.WALKING:
            return "walk_right" if self._direction > 0 else "walk_left"
        if self._state == PetState.RUNNING:
            return "run_right" if self._direction > 0 else "run_left"
        return STATE_ANIMATION_MAP.get(self._state, "idle")

    def resume_previous(self):
        """Go back to the previous state (e.g., after dragging)."""
        self.set_state(self._previous_state)
