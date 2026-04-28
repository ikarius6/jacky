"""SpeechMixin — speech bubble display, TTS playback, and STT toggle."""

import logging

from PyQt6.QtCore import Qt

from core.pet import PetState
from utils.i18n import t
from core.mixins.utils import REVERT_TAG

log = logging.getLogger("pet_window")


class SpeechMixin:
    """Mixin providing speech bubble management, TTS callbacks, and STT toggle."""

    # ── Public speech API ─────────────────────────────────────────────────────

    def _say(self, text: str | None, timeout_ms: int = 0, force: bool = False,
             skip_voice: bool = False):
        """Show a speech bubble with text.

        timeout_ms: override auto-calculated timeout (0 = auto).
        force: if True, ignore silent mode (used for direct user questions).
        skip_voice: if True, skips Text-to-Speech playback.
        """
        # --- Appearance easter egg text effects ---
        if text and text.startswith(REVERT_TAG):
            text = text[len(REVERT_TAG):]  # strip sentinel, no effect applied
        elif text and self._appearance_mode == "evil":
            if not text.rstrip().endswith("muajaja~") and not text.rstrip().endswith("muahaha~"):
                text = text.rstrip() + " muajaja~"
        elif text and self._appearance_mode == "glitch":
            text = text[::-1]

        if not text:
            return
        if self._pending_organize is not None:
            return
        if self._silent_mode and not force:
            return

        # Mark Jacky as speaking so autonomous events don't interrupt
        self._is_speaking = True

        mode = self._config.get("response_mode", "both")
        if mode in ("voice", "both") and not skip_voice:
            self._tts_client.play_tts(text)
            if mode == "voice":
                self._bubble.hide()
                self.pet.set_state(PetState.TALKING)
                self._talk_end_timer.start(max(3000, len(text) * 50))
                return

        log.info("SAY state=%s pos=(%d,%d) text='%s'",
                 self.pet.state.name, self.x(), self.y(), text[:80])
        old_state = self.pet.state
        _KEEP_ANIM = (PetState.HAPPY, PetState.EATING, PetState.DRAGGED,
                     PetState.ATTACKING, PetState.HURT,
                     PetState.DYING, PetState.WALKING, PetState.RUNNING,
                     PetState.DANCE, PetState.GETTING_PET)
        if old_state not in _KEEP_ANIM:
            self.pet.set_state(PetState.TALKING)

        anchor_x = self.x() + self._sprite_size // 2
        anchor_y = self.y()
        if timeout_ms <= 0:
            min_timeout = self._config.get("bubble_timeout", 5) * 1000
            word_count = len(text.split())
            timeout_ms = max(min_timeout, int(word_count * 400))
        self._bubble.show_message(text, anchor_x, anchor_y, timeout_ms=timeout_ms,
                                  pet_height=self._sprite_size)

        # When bubble is shown, bring pet to the exact same top z-order
        self._reassert_topmost()

        # Return to IDLE after bubble hides
        if old_state not in _KEEP_ANIM:
            self._talk_end_timer.start(timeout_ms)

    def _say_forced(self, text: str | None):
        """Show speech bubble ignoring silent mode (for direct user questions)."""
        self._say(text, force=True)

    # ── TTS callbacks ─────────────────────────────────────────────────────────

    def _end_talk_to_idle(self):
        self._is_speaking = False
        if self.pet.state == PetState.TALKING:
            log.debug("END_TALK -> IDLE pos=(%d,%d)", self.x(), self.y())
            self.pet.set_state(PetState.IDLE)

    def _on_tts_finished(self):
        """Called when ElevenLabs TTS playback ends — release the speaking lock."""
        self._is_speaking = False
        log.debug("TTS_DONE speaking lock released")

    # ── Thinking indicator ────────────────────────────────────────────────────

    def _show_thinking(self):
        """Show animated thinking indicator in the speech bubble."""
        self.pet.set_state(PetState.TALKING)
        anchor_x = self.x() + self._sprite_size // 2
        anchor_y = self.y()
        self._bubble.show_thinking(anchor_x, anchor_y, pet_height=self._sprite_size)
        self._reassert_topmost()

    # ── Bubble position tracking ──────────────────────────────────────────────

    def _update_bubble_pos(self):
        anchor_x = self.x() + self._sprite_size // 2
        anchor_y = self.y()
        if self._bubble.isVisible():
            self._bubble.update_position(anchor_x, anchor_y)
        if self._confirm_buttons.isVisible():
            self._confirm_buttons.update_position(anchor_x, anchor_y)
        if hasattr(self, '_music_player') and self._music_player.isVisible():
            self._music_player.update_position(anchor_x, anchor_y)

    # ── STT / listen toggle ───────────────────────────────────────────────────

    def on_listen_toggle(self):
        """Toggle microphone recording for voice STT."""
        self._touch_user_interaction()
        if not self._config.get("assemblyai_api_key", "").strip():
            return

        if getattr(self._stt_client, "_is_recording", False):
            self._listen_timeout.stop()
            self._bubble.hide()
            self._stt_client.stop_listening()
        else:
            max_sec = self._config.get("listen_timeout_seconds", 60)
            self._say(t("ui.listening"), force=True, timeout_ms=max_sec * 1000, skip_voice=True)
            self._stt_client.start_listening()
            self._listen_timeout.start(max_sec * 1000)

    def _on_listen_timeout(self):
        """Auto-stop listening when the max recording duration expires."""
        if getattr(self._stt_client, "_is_recording", False):
            log.info("Listen timeout reached, auto-stopping STT")
            self._bubble.hide()
            self._stt_client.stop_listening()
