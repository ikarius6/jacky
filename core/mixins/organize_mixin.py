"""OrganizeMixin — desktop file organize flow: scan → LLM categorize → confirm → execute."""

import logging
import threading

from speech.dialogue import get_line
from utils.i18n import get_confirm_words
from core.mixins.utils import match_words

log = logging.getLogger("pet_window")


class OrganizeMixin:
    """Mixin handling the full desktop organize flow from routine trigger to execution."""

    _AFFIRM_FALLBACK = {"yes", "ok", "sure", "sí", "si", "dale", "adelante"}
    _DENY_FALLBACK = {"no", "nope", "cancel", "cancela"}

    # ── Routine organize trigger ──────────────────────────────────────────────

    def _on_organize_proposal(self, routine_id: str, files_json: str, confirm_msg: str, target_folder: str = ""):
        """Handle the organize action from the routine engine.

        1. Say the confirm_msg while processing.
        2. If LLM enabled → ask it to categorize the files.
        3. If LLM disabled → use extension-based fallback.
        4. Present the proposal and wait for user confirmation.
        """
        import json as _json
        try:
            files = _json.loads(files_json)
        except (ValueError, TypeError):
            files = []

        if not files:
            self._say(get_line("organize_empty", self.pet.name), force=True)
            return

        self._organize_real_files = files
        self._organize_target_folder = target_folder or ""

        if confirm_msg:
            self._say(confirm_msg, force=True)
        else:
            self._say(get_line("organize_scanning", self.pet.name), force=True)

        if self._llm_enabled:
            file_list_str = _json.dumps(files, ensure_ascii=False)
            prompt_text = self._build_organize_prompt(file_list_str)
            context = self._build_llm_context(prompt_text)

            def _on_result(text):
                self._organize_ready.emit(text if text else "")

            self._llm.generate(context, _on_result)
        else:
            from utils.desktop_organizer import categorize_by_extension
            plan = categorize_by_extension(files)
            self._present_organize_plan(plan)

    def _build_organize_prompt(self, file_list_str: str) -> str:
        from utils.i18n import t
        return t("llm_prompts.organize_categorize", file_list=file_list_str)

    # ── LLM categorization response ───────────────────────────────────────────

    def _on_organize_llm_response(self, response: str):
        """Handle the LLM categorization response (main thread via signal)."""
        import json as _json
        from utils.desktop_organizer import categorize_by_extension

        real_files = getattr(self, "_organize_real_files", [])
        real_names = {f["name"] for f in real_files}

        plan = None
        if response:
            try:
                plan = _json.loads(response)
            except (ValueError, TypeError):
                import re
                match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response)
                if match:
                    try:
                        plan = _json.loads(match.group())
                    except (ValueError, TypeError):
                        pass

        if plan and isinstance(plan, dict):
            validated: dict[str, list[str]] = {}
            matched = 0
            for folder, names in plan.items():
                if not isinstance(names, list):
                    continue
                good = [n for n in names if n in real_names]
                matched += len(good)
                if good:
                    validated[folder] = good
            if matched >= len(real_names) // 2 and validated:
                plan = validated
                log.info("LLM organize plan validated: %d/%d files matched",
                         matched, len(real_names))
            else:
                log.warning("LLM plan matched only %d/%d files, falling back",
                            matched, len(real_names))
                plan = None

        if not plan:
            plan = categorize_by_extension(real_files)

        self._present_organize_plan(plan)

    # ── Present proposal ──────────────────────────────────────────────────────

    def _present_organize_plan(self, plan: dict):
        """Show the organize plan to the user and wait for confirmation."""
        from utils.desktop_organizer import format_plan_summary
        plan = {k: v for k, v in plan.items() if v}
        if not plan:
            self._say(get_line("organize_empty", self.pet.name), force=True)
            return

        summary = format_plan_summary(plan)
        proposal_line = get_line("organize_proposal", self.pet.name, summary=summary)
        if not proposal_line:
            proposal_line = f"🗂️ {summary} — ¿Lo hago?"
        self._say(proposal_line, force=True, timeout_ms=15000)
        # Set AFTER _say so the guard in _say doesn't block our own proposal
        self._pending_organize = plan
        self._confirm_buttons.show_at(
            self.x() + self._sprite_size // 2,
            self.y(),
            pet_height=self._sprite_size,
        )

    # ── Confirm/deny buttons ──────────────────────────────────────────────────

    def _on_confirm_button(self, accepted: bool):
        """Handle click on the GUI Yes/No buttons."""
        self._confirm_buttons.hide()
        if self._pending_organize is None:
            return
        self._handle_organize_confirmation("sí" if accepted else "no")

    # ── Confirmation logic ────────────────────────────────────────────────────

    def _handle_organize_confirmation(self, question: str):
        """Check if user said yes or no to the pending organize plan."""
        q_lower = question.strip().lower()
        plan = self._pending_organize

        affirm, deny = get_confirm_words()
        affirm = affirm or self._AFFIRM_FALLBACK
        deny = deny or self._DENY_FALLBACK

        if match_words(q_lower, affirm):
            self._confirm_buttons.hide()
            self._pending_organize = None
            self._say(get_line("organize_executing", self.pet.name), force=True)

            def _do_move():
                import pathlib
                from utils.desktop_organizer import execute_organize_plan
                target = getattr(self, "_organize_target_folder", "")
                folder = pathlib.Path(target) if target else None
                result = execute_organize_plan(plan, desktop=folder)
                moved_count = len(result.get("moved", []))
                error_count = len(result.get("errors", []))
                if error_count:
                    line = get_line("organize_done_partial", self.pet.name,
                                    moved=moved_count, errors=error_count)
                else:
                    line = get_line("organize_done", self.pet.name, moved=moved_count)
                if not line:
                    line = f"🗂️ ¡Listo! Moví {moved_count} archivos."
                self._llm_ask_ready.emit(line)

            threading.Thread(target=_do_move, name="organize-exec", daemon=True).start()

        elif match_words(q_lower, deny):
            self._confirm_buttons.hide()
            self._pending_organize = None
            self._say(get_line("organize_cancelled", self.pet.name), force=True)
        else:
            # Unrecognized — ask again
            self._pending_organize = None
            from core.pet import PetState
            self.pet.set_state(PetState.CONFUSED)
            self._say(get_line("organize_confirm_retry", self.pet.name), force=True)
            self._pending_organize = plan
