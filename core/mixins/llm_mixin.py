"""LlmMixin — LLM context building, response callbacks, and vision helpers."""

import random
import datetime
import logging

from core.pet import PetState
from utils.i18n import t
from utils.screen_capture import capture_vision_area
from speech.dialogue import get_line

log = logging.getLogger("pet_window")


class LlmMixin:
    """Mixin providing LLM call helpers and thread-safe response callbacks."""

    # ── Context building ──────────────────────────────────────────────────────

    def _build_llm_context(self, situation: str) -> str:
        parts = [f"Situation: {situation}"]
        interesting = self._window_awareness.get_interesting_windows()
        if interesting:
            pick = random.choice(interesting)
            parts.append(f"Foreground app: {pick.title}")
        hour = datetime.datetime.now().hour
        if hour >= 23 or hour < 5:
            parts.append(f"Current time: {datetime.datetime.now().strftime('%H:%M')}")
        return " | ".join(parts)

    # ── Response callbacks ────────────────────────────────────────────────────

    def _on_llm_response(self, text: str | None):
        """Callback from LLM thread — emit signal for thread-safe delivery."""
        self._llm_pending = False
        if text:
            self._llm_text_ready.emit(text)
        else:
            fallback = get_line("idle", self.pet.name) or "..."
            self._llm_text_ready.emit(fallback)

    def _on_ask_response(self, text: str | None):
        """Callback from LLM for user questions — shows error on failure."""
        self._llm_pending = False
        if text:
            self._llm_ask_ready.emit(text)
        else:
            self._llm_ask_ready.emit(t("ui.llm_error"))

    # ── Vision helpers ────────────────────────────────────────────────────────

    def _needs_vision(self, text: str) -> bool:
        """Check if the user's question contains vision trigger words."""
        from utils.i18n import get_vision_keywords
        words = set(text.lower().split())
        return bool(words & get_vision_keywords())

    def _capture_vision(self) -> str:
        """Capture the 1024x1024 vision area centred on the pet and return base64 PNG."""
        cx = self.x() + self._sprite_size // 2
        cy = self.y() + self._sprite_size // 2
        screen = self._current_screen()
        dpi = screen.devicePixelRatio() if screen else 1.0
        return capture_vision_area(cx, cy, dpi_scale=dpi)

    def _ask_direct_or_vision(self, question: str):
        """Send the question to the LLM using vision or text based on keywords/permissions."""
        if self._needs_vision(question) and self._perm("allow_vision"):
            self.pet.set_state(PetState.TAKING_PICTURE)
            context = self._build_llm_context(t("llm_prompts.ask_vision", question=question))
            image_b64 = self._capture_vision()
            self._llm.generate_with_image(context, image_b64, self._on_ask_response)
        else:
            context = self._build_llm_context(t("llm_prompts.ask_direct", question=question))
            self._llm.generate(context, self._on_ask_response)
