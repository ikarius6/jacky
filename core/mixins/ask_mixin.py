"""AskMixin — user question pipeline: intent classification, screen interaction, vision."""

import logging

from core.pet import PetState
from core.screen_interaction.intent_classifier import classify_intent, IntentResult
from core.screen_interaction.constants import INTENT_CONFIDENCE_THRESHOLD
from utils.i18n import t

log = logging.getLogger("pet_window")


class AskMixin:
    """Mixin handling on_ask(), intent classification, on_look(), and screen-task dispatch."""

    # ── Screen movement helper ────────────────────────────────────────────────

    def _move_to_screen_target(self, qt_x: int, qt_y: int):
        """Run the pet toward a screen-interaction target (Qt logical coords)."""
        target_x = qt_x - self._sprite_size // 2
        target_y = qt_y - self._sprite_size // 2
        bounds = self.movement._get_bounds()
        target_x = max(bounds[0], min(target_x, bounds[2] - self._sprite_size))
        target_y = max(bounds[1], min(target_y, bounds[3] - self._sprite_size))
        self.movement._target_x = target_x
        self.movement._target_y = target_y
        self.movement._direction = 1 if target_x > self.movement._x else -1
        if "run" in self.animation.available_states:
            self.pet.set_state(PetState.RUNNING)
        else:
            self.pet.set_state(PetState.WALKING)

    # ── Screen task dispatch ──────────────────────────────────────────────────

    def _start_screen_task(self, action_type: str, target_desc: str,
                           type_text_content: str = None):
        """Validate permissions and start a screen interaction task."""
        if not self._perm("allow_vision"):
            self._say(t("ui.no_vision_perm"), force=True)
            return
        if action_type != "navigate" and not self._perm("allow_screen_interact"):
            self._say(t("ui.no_interact_perm"), force=True)
            return
        if self._screen_interaction.is_active:
            self._screen_interaction.cancel(say_line=False)
        if self._llm_pending:
            self._llm_pending = False
        self._screen_interaction.start_task(action_type, target_desc,
                                            type_text_content=type_text_content)

    # ── Main ask entry-point ──────────────────────────────────────────────────

    def on_ask(self, question: str):
        """User asked a direct question via the Preguntar dialog.

        Flow:
        0. If there's a pending organize plan, check for yes/no confirmation
        1. Fast path — keyword matching (no LLM call)
        2. Fallback — LLM intent classification
        3. Based on LLM result → screen interaction, vision, or chat
        """
        self._touch_user_interaction()

        # ── Organize confirmation interception ──
        if self._pending_organize is not None:
            self._handle_organize_confirmation(question)
            return

        # ── Easter egg fast path ──
        if self._check_easter_egg(question):
            return

        if not self._llm_enabled:
            matched_routine = self._routine_manager.try_match_keyword(question)
            if matched_routine:
                self._routine_manager.run_routine(matched_routine.id)
            return

        # ── Fast path: routine keyword matching ──
        matched_routine = self._routine_manager.try_match_keyword(question)
        if matched_routine:
            self._show_thinking()
            self._routine_manager.run_routine(matched_routine.id)
            return

        # ── Fast path: screen interaction keyword matching ──
        parsed = self._screen_interaction.try_parse_interaction(question)
        if parsed:
            action_type, target_desc, type_text_content = parsed
            self._start_screen_task(action_type, target_desc,
                                    type_text_content=type_text_content)
            return

        if self._llm_pending:
            self._say(t("ui.busy"), force=True)
            return
        self._llm_pending = True
        self._pending_question = question
        self._show_thinking()

        # ── Fallback: LLM intent classification ──
        def _on_result(result):
            self._intent_ready.emit(result)

        routine_ctx = self._routine_manager.get_routine_context_for_llm()
        classify_intent(question, self._llm, _on_result, routine_context=routine_ctx)

    # ── Intent classification result ──────────────────────────────────────────

    def _on_intent_classified(self, result):
        """Handle the LLM intent classification result (runs on main thread via signal)."""
        question = self._pending_question
        self._pending_question = ""

        if result is None or result.confidence < INTENT_CONFIDENCE_THRESHOLD:
            log.info("INTENT fallback to chat (result=%s)", result)
            self._ask_direct_or_vision(question)
            return

        log.info("INTENT classified: %s conf=%d target=%r",
                 result.intent, result.confidence, result.target)

        if result.is_interaction and result.target:
            self._llm_pending = False
            self._bubble.hide()
            self._start_screen_task(result.intent, result.target,
                                    type_text_content=result.type_text or None)
        elif result.is_timer:
            self._llm_pending = False
            self._bubble.hide()
            self._handle_timer_intent(result)
        elif result.intent == "routine" and result.routine_id:
            self._llm_pending = False
            routine = self._routine_manager.get_routine_by_id(result.routine_id)
            if routine:
                log.info("INTENT routine id=%s", result.routine_id)
                self._routine_manager.run_routine(routine.id)
            else:
                self._ask_direct_or_vision(question)
        elif result.intent == "vision":
            if self._perm("allow_vision"):
                context = self._build_llm_context(t("llm_prompts.ask_vision", question=question))
                image_b64 = self._capture_vision()
                self._llm.generate_with_image(context, image_b64, self._on_ask_response)
            else:
                self._ask_direct_or_vision(question)
        else:
            self._ask_direct_or_vision(question)

    # ── Look action ───────────────────────────────────────────────────────────

    def on_look(self):
        """Context-menu action: pet looks at the screen and comments on what it sees."""
        self._touch_user_interaction()
        if not self._llm_enabled:
            self._say(t("ui.no_llm"), force=True)
            return
        if not self._perm("allow_vision"):
            self._say(t("ui.no_vision_perm"), force=True)
            return
        if self._llm_pending:
            self._say(t("ui.busy"), force=True)
            return
        self._llm_pending = True
        self._show_thinking()
        context = self._build_llm_context(t("llm_prompts.action_look"))
        image_b64 = self._capture_vision()
        self._llm.generate_with_image(context, image_b64, self._on_ask_response)
