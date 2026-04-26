"""BoredomMixin — boredom escalation ladder and idle-neglect easter egg."""

import time
import logging

from PyQt6.QtCore import QTimer

from core.pet import PetState
from speech.dialogue import get_line
from utils.i18n import t

log = logging.getLogger("pet_window")


class BoredomMixin:
    """Mixin providing boredom escalation: callout → erratic → selftalk → sleep."""

    # ── User-interaction tracking ─────────────────────────────────────────────

    def _touch_user_interaction(self):
        """Record that the user just interacted with Jacky. Resets boredom and wakes if asleep."""
        self._last_user_interaction = time.monotonic()
        if self._boredom_asleep:
            self._wake_up()
        elif self._boredom_level > 0:
            log.info("BOREDOM reset (was level %d)", self._boredom_level)
            self._boredom_level = 0

    # ── Periodic boredom check ────────────────────────────────────────────────

    def _check_boredom(self):
        """Periodic check (every 60s) — escalate boredom if user hasn't interacted."""
        if self._gamer_mode or self._boredom_asleep:
            return
        elapsed_min = (time.monotonic() - self._last_user_interaction) / 60.0

        if elapsed_min >= self._BOREDOM_ASLEEP_MIN and self._boredom_level < 4:
            self._boredom_level = 4
            self._boredom_sleep()
        elif elapsed_min >= self._BOREDOM_SELFTALK_MIN and self._boredom_level < 3:
            self._boredom_level = 3
            self._say(get_line("bored_selftalk", self.pet.name))
            self.pet.set_state(PetState.IDLE)
            self._last_selftalk = time.monotonic()
        elif elapsed_min >= self._BOREDOM_SELFTALK_MIN and self._boredom_level == 3:
            now = time.monotonic()
            if (now - self._last_selftalk) >= self._BOREDOM_SELFTALK_INTERVAL_S:
                self._boredom_selftalk()
                self._last_selftalk = now
        elif elapsed_min >= self._BOREDOM_ERRATIC_MIN and self._boredom_level < 2:
            self._boredom_level = 2
            self._boredom_erratic_walk()
        elif elapsed_min >= self._BOREDOM_CALLOUT_MIN and self._boredom_level < 1:
            self._boredom_level = 1
            log.info("BOREDOM callout (%.1f min idle)", elapsed_min)
            self._say(get_line("bored_callout", self.pet.name))

    # ── Escalation stages ─────────────────────────────────────────────────────

    def _boredom_erratic_walk(self):
        """Boredom level 2: walk erratically with random direction changes."""
        log.info("BOREDOM erratic walk")
        self._say(get_line("bored_erratic", self.pet.name))
        self.movement.pick_random_target()
        self.pet.set_state(PetState.WALKING)
        for i in range(3):
            QTimer.singleShot(2000 * (i + 1), self._boredom_erratic_step)

    def _boredom_erratic_step(self):
        """One step of erratic walking: pick a new random target and flip direction."""
        if self._boredom_level < 2 or self._boredom_asleep:
            return
        if self.pet.state not in (PetState.IDLE, PetState.WALKING):
            return
        self.pet.direction = -self.pet.direction
        self.movement.pick_random_target()
        if self.pet.state == PetState.IDLE:
            self.pet.set_state(PetState.WALKING)

    def _boredom_selftalk(self):
        """Boredom level 3: LLM self-talk monologue or predefined fallback."""
        if self._llm_enabled and not self._llm_pending:
            self._llm_pending = True
            context = self._build_llm_context(t("llm_prompts.idle_selftalk"))
            self._llm.generate(context, self._on_selftalk_response)
        else:
            self._say(get_line("bored_selftalk", self.pet.name))

    def _on_selftalk_response(self, text: str | None):
        """Callback from LLM for self-talk — thread-safe via signal."""
        self._llm_pending = False
        if text:
            self._llm_text_ready.emit(text)
        else:
            fallback = get_line("bored_selftalk", self.pet.name) or "..."
            self._llm_text_ready.emit(fallback)

    def _boredom_sleep(self):
        """Boredom level 4: fall asleep — DYING animation, pause scheduler."""
        log.info("BOREDOM asleep")
        self._boredom_asleep = True
        self._say(get_line("bored_asleep", self.pet.name))
        self.pet.set_state(PetState.DYING)
        self.scheduler.pause_all()

    def _wake_up(self):
        """Wake Jacky from boredom sleep — HAPPY animation, resume scheduler."""
        log.info("BOREDOM wakeup")
        self._boredom_asleep = False
        self._boredom_level = 0
        self.scheduler.resume_all()
        self.pet.set_state(PetState.HAPPY)
        self._temp_state_timer.start(3000)
        self._say(get_line("bored_wakeup", self.pet.name), force=True)
