"""RoutineMixin — callbacks for routine say / notify / log / failed actions."""

import logging

log = logging.getLogger("pet_window")


class RoutineMixin:
    """Mixin handling all signal callbacks emitted by RoutineManager."""

    def _on_routine_say(self, routine_id: str, llm_text: str, nollm_text: str):
        """Handle a routine 'say' action."""
        if llm_text and self._llm_enabled:
            context = self._build_llm_context(llm_text)
            self._llm.generate(context, self._on_ask_response)
        elif nollm_text:
            self._say(nollm_text, force=True)
        elif llm_text:
            self._say(llm_text, force=True)

    def _on_routine_notify(self, routine_id: str, title: str, message: str):
        """Handle a routine 'notification' action — show a tray notification."""
        self._tray.showMessage(title, message)

    def _on_routine_log(self, routine_id: str, message: str):
        """Handle a routine 'log' action — write to the log only."""
        log.info("ROUTINE_LOG id=%s: %s", routine_id, message)

    def _on_routine_failed(self, routine_id: str, error_msg: str):
        """Handle a routine failure — log and optionally inform the user."""
        log.error("ROUTINE_FAILED id=%s: %s", routine_id, error_msg)
