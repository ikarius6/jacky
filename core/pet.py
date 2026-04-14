import logging
from enum import Enum, auto
from typing import Optional, Callable, List

log = logging.getLogger("pet")


class PetState(Enum):
    IDLE = auto()
    TALKING = auto()
    WALKING = auto()
    RUNNING = auto()
    HURT = auto()
    HAPPY = auto()
    FALLING = auto()
    JUMPING = auto()
    ATTACKING = auto()
    EATING = auto()
    DRAGGED = auto()
    DYING = auto()
    DANCE = auto()
    GETTING_PET = auto()
    PEEKING = auto()


# Maps pet states to animation state names (sprite prefixes)
STATE_ANIMATION_MAP = {
    PetState.IDLE: "idle",
    PetState.TALKING: "talk",
    PetState.WALKING: "walk",
    PetState.RUNNING: "run",
    PetState.HURT: "hurt",
    PetState.HAPPY: "happy",
    PetState.FALLING: "falling",
    PetState.JUMPING: "jump_loop",
    PetState.ATTACKING: "shooting",
    PetState.EATING: "happy",
    PetState.DRAGGED: "drag",
    PetState.DYING: "dying",
    PetState.DANCE: "happy",
    PetState.GETTING_PET: "happy",
    PetState.PEEKING: "idle",
}

# Fallback chains for states whose primary animation may not exist in all sprite packs.
# When the primary animation name (from STATE_ANIMATION_MAP) is not available,
# try these alternatives in order.
ANIMATION_FALLBACKS: dict[str, list[str]] = {
    "shooting": ["slashing", "kick"],
    "happy":    ["kick"],
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
        old = self._direction
        self._direction = 1 if value >= 0 else -1
        if old != self._direction:
            log.debug("DIRECTION %s -> %s", 'R' if old > 0 else 'L', 'R' if self._direction > 0 else 'L')

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
        log.info("STATE %s -> %s", old.name, new_state.name)
        for cb in self._on_state_change:
            cb(old, new_state)

    def get_animation_name(self) -> str:
        """Return the animation state name for the current pet state.

        Direction is handled externally via AnimationController.set_facing(),
        so only a single state name is needed for walking and running.
        """
        return STATE_ANIMATION_MAP.get(self._state, "idle")

    def resume_previous(self):
        """Go back to the previous state (e.g., after dragging)."""
        self.set_state(self._previous_state)
