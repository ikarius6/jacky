"""EasterEggMixin — all Easter egg handlers (barrel roll, dizzy, evil, glitch, etc.)."""

import random
import logging

from PyQt6.QtCore import QTimer

from core.pet import PetState
from speech.dialogue import get_line
from utils.i18n import get_easter_keywords
from core.mixins.utils import REVERT_TAG, match_words

log = logging.getLogger("pet_window")


class EasterEggMixin:
    """Mixin providing Easter egg detection and all individual Easter egg handlers."""

    # ── Detection ─────────────────────────────────────────────────────────────

    def _check_easter_egg(self, question: str) -> bool:
        """Match *question* against easter-egg trigger phrases.

        Returns True if an easter egg was triggered (caller should return early).
        """
        q_lower = question.lower().strip()
        easter_kw = get_easter_keywords()
        for egg_name, phrases in easter_kw.items():
            phrase_set = set(phrases)
            if match_words(q_lower, phrase_set):
                handler = getattr(self, f"_easter_{egg_name}", None)
                if handler:
                    log.info("EASTER_EGG %s triggered by '%s'", egg_name, question[:60])
                    handler()
                    return True
        return False

    # ── Dizzy (rapid clicks / long drag) ─────────────────────────────────────

    def on_dizzy(self):
        """Easter egg: rapid clicks or long drag made Jacky dizzy."""
        if self.pet.state == PetState.HURT:
            return
        log.info("EASTER_EGG dizzy meltdown pos=(%d,%d)", self.x(), self.y())
        self.pet.set_state(PetState.HURT)
        self._say(get_line("dizzy", self.pet.name))
        self._temp_state_timer.start(5000)
        QTimer.singleShot(5000, self._dizzy_recover)

    def _dizzy_recover(self):
        """Recovery line after dizzy meltdown."""
        line = get_line("dizzy_recover", self.pet.name)
        if line:
            self._say(line)

    # ── Barrel roll ───────────────────────────────────────────────────────────

    def _easter_barrel_roll(self):
        """Barrel roll: rapid sprite flip L→R→L→R (8 flips, 150ms each)."""
        self._say(get_line("easter_barrel_roll", self.pet.name), force=True)
        self._barrel_roll_count = 0
        self._barrel_roll_timer.start()

    def _barrel_roll_tick(self):
        """One tick of the barrel-roll flip animation."""
        self._barrel_roll_count += 1
        self.pet.direction = -self.pet.direction
        if self._barrel_roll_count >= 8:
            self._barrel_roll_timer.stop()
            self._barrel_roll_count = 0

    # ── Play dead ─────────────────────────────────────────────────────────────

    def _easter_play_dead(self):
        """Play dead: DYING animation for 5s, then revive with a joke."""
        self._say(get_line("easter_play_dead", self.pet.name), force=True)
        self.pet.set_state(PetState.DYING)
        self._temp_state_timer.start(5000)
        QTimer.singleShot(5000, self._play_dead_revive)

    def _play_dead_revive(self):
        """Revive after playing dead."""
        line = get_line("easter_play_dead_revive", self.pet.name)
        if line:
            self._say(line, force=True)

    # ── Dance ─────────────────────────────────────────────────────────────────

    def _easter_dance(self):
        """Forced dance for 10 seconds."""
        self._say(get_line("easter_dance", self.pet.name), force=True)
        self.pet.set_state(PetState.DANCE)
        self._temp_state_timer.start(10000)

    # ── Evil mode ─────────────────────────────────────────────────────────────

    def _easter_evil(self):
        """Evil mode: inverted color palette for 30 s. All dialogue ends with 'muajaja~'."""
        log.info("EASTER_EGG evil mode activated")
        self._appearance_mode = "evil"
        self._glitch_tick_timer.stop()
        self._say(get_line("easter_evil", self.pet.name), force=True)
        self._appearance_timer.start(30_000)
        self.update()

    # ── Glitch mode ───────────────────────────────────────────────────────────

    def _easter_glitch(self):
        """Glitch mode: flipped sprite + random color tint for 30 s. Dialogue is reversed."""
        log.info("EASTER_EGG glitch mode activated")
        self._appearance_mode = "glitch"
        self._glitch_tick_timer.start()
        self._say(get_line("easter_glitch", self.pet.name), force=True)
        self._appearance_timer.start(30_000)
        self.update()

    def _glitch_tick(self):
        """Randomise the glitch tint color each tick so it flickers."""
        self._glitch_color_r = random.randint(0, 255)
        self._glitch_color_g = random.randint(0, 255)
        self._glitch_color_b = random.randint(0, 255)
        self.update()

    # ── Appearance revert ─────────────────────────────────────────────────────

    def _revert_appearance(self):
        """Restore Jacky's normal appearance after the easter egg timer expires."""
        prev_mode = self._appearance_mode
        self._appearance_mode = None
        self._glitch_tick_timer.stop()
        self.update()
        if prev_mode == "evil":
            line = get_line("easter_evil_revert", self.pet.name)
        else:
            line = get_line("easter_glitch_revert", self.pet.name)
        if line:
            self._say(REVERT_TAG + line, force=True)
