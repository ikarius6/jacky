import logging
import random
from enum import Enum, auto
from typing import Optional, Callable, List, Union

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
    SLEEPING = auto()
    TAKING_NOTES = auto()
    ERROR = auto()
    TAKING_PICTURE = auto()
    ROCKING = auto()
    CONFUSED = auto()
    DIZZY = auto()
    THINKING = auto()
    LOADING = auto()
    TYPING = auto()
    ALERTING = auto()


# Maps pet states to animation state names (sprite prefixes).
# Values can be a single string or a list of strings.  When a list is given
# one variant is chosen at random on each state transition so that repeated
# visits to the same state look varied (e.g. ["idle", "idle2", "idle3"]).
STATE_ANIMATION_MAP: dict[PetState, Union[str, list[str]]] = {
    PetState.IDLE:           ["idle", "idle2"],
    PetState.TALKING:        ["talk"],
    PetState.WALKING:        ["walk"],
    PetState.RUNNING:        ["run"],
    PetState.HURT:           ["hurt"],
    PetState.HAPPY:          ["happy", "happy2"],
    PetState.FALLING:        ["falling"],
    PetState.JUMPING:        ["jump_loop"],
    PetState.ATTACKING:      ["shooting"],
    PetState.EATING:         ["eating"],
    PetState.DRAGGED:        ["drag"],
    PetState.DYING:          ["dying"],
    PetState.DANCE:          ["dance"],
    PetState.GETTING_PET:    ["getting_pet", "getting_pet2", "getting_pet3"],
    PetState.PEEKING:        ["peeking"],
    PetState.SLEEPING:       ["sleeping"],
    PetState.TAKING_NOTES:   ["taking_notes"],
    PetState.ERROR:          ["error"],
    PetState.TAKING_PICTURE: ["taking_picture"],
    PetState.ROCKING:        ["rocking"],
    PetState.CONFUSED:       ["confused"],
    PetState.DIZZY:          ["dizzy"],
    PetState.THINKING:       ["thinking"],
    PetState.LOADING:        ["loading"],
    PetState.TYPING:         ["typing", "typing2"],
    PetState.ALERTING:       ["alerting"],
}

# Fallback chains for states whose primary animation may not exist in all sprite packs.
# When the primary animation name (from STATE_ANIMATION_MAP) is not available,
# try these alternatives in order.  "idle" is always the implicit last resort
# (handled in Pet.get_animation_name), so it does not need to appear here for
# every entry, but it is included where a meaningful intermediate exists.
ANIMATION_FALLBACKS: dict[str, list[str]] = {
    "idle2":          ["idle"],
    "walk":           ["idle"],
    "run":            ["walk", "idle"],
    "kick":           ["idle"],
    "shooting":       ["slashing", "kick"],
    "happy":          ["kick"],
    "eating":         ["happy"],
    "dance":          ["happy"],
    "getting_pet":    ["happy"],
    "peeking":        ["idle"],
    "sleeping":       ["idle"],
    "talk":           ["idle_blink"],
    "taking_notes":   ["talk", "idle"],
    "error":          ["hurt", "idle"],
    "taking_picture": ["idle"],
    "rocking":        ["happy", "kick", "idle"],
    "confused":       ["idle_blink", "idle"],
    "dizzy":          ["hurt", "idle"],
    "thinking":       ["idle_blink", "idle"],
    "loading":        ["idle_blink", "idle"],
    "typing":         ["talk", "idle"],
    "alerting":       ["talk", "idle"],
    "getting_pet2":   ["getting_pet"],
    "getting_pet3":   ["getting_pet"],
    "happy2":         ["happy"],
    "typing2":        ["typing"],
    "drag":           ["hurt", "idle"],
    "falling":        ["hurt", "idle"],
}


class Pet:
    """Pet state machine — manages Jacky's current state and transitions."""

    def __init__(self, name: str = "Jacky"):
        self.name = name
        self._state = PetState.IDLE
        self._previous_state = PetState.IDLE
        self._direction = 1  # 1 = right, -1 = left
        self._on_state_change: List[Callable[[PetState, PetState], None]] = []
        # Cached animation variant chosen on the last state transition.
        self._resolved_anim: Optional[str] = None

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
        self._resolved_anim = None  # force re-roll on next get_animation_name()
        log.info("STATE %s -> %s", old.name, new_state.name)
        for cb in self._on_state_change:
            cb(old, new_state)

    def get_animation_name(self) -> str:
        """Return the animation state name for the current pet state.

        When a state maps to multiple animation variants the choice is made
        once per state transition and cached so the same variant plays until
        the state changes again.

        Direction is handled externally via AnimationController.set_facing(),
        so only a single state name is needed for walking and running.
        """
        if self._resolved_anim is not None:
            return self._resolved_anim

        entry = STATE_ANIMATION_MAP.get(self._state, "idle")
        if isinstance(entry, list):
            self._resolved_anim = random.choice(entry)
        else:
            self._resolved_anim = entry
        return self._resolved_anim

    def reroll_animation(self) -> str:
        """Force a new random variant pick for the current state.

        Useful for long-lived states (like IDLE) where you want periodic
        variety without a full state transition.
        """
        self._resolved_anim = None
        return self.get_animation_name()

    def resume_previous(self):
        """Go back to the previous state (e.g., after dragging)."""
        self.set_state(self._previous_state)
