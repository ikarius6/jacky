"""Routine manager — scheduling, trigger matching, and execution.

Owns all loaded routines, manages QTimers for automatic ones, and
provides keyword/LLM trigger matching for manual routines.  All HTTP
work runs in background threads; results arrive via pyqtSignal.
"""

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from core.routines.loader import load_routines, _resolve_routines_dir
from core.routines.models import RoutineDefinition, RoutineAction
from core.routines.engine import run_routine, RoutineResult

log = logging.getLogger("routines.manager")


class RoutineManager(QObject):
    """Central manager for all routines."""

    # action_type: "say" | "notification" | "log"
    # llm_text: the prompt for the LLM
    # nollm_text: the literal fallback string if LLM is disabled
    routine_say = pyqtSignal(str, str, str)           # routine_id, llm_text, nollm_text
    routine_notify = pyqtSignal(str, str, str)         # routine_id, title, message
    routine_log = pyqtSignal(str, str)                 # routine_id, message
    routine_organize = pyqtSignal(str, str, str, str)  # routine_id, files_json, confirm_msg, target_folder
    routine_failed = pyqtSignal(str, str)              # routine_id, error_msg
    routine_done = pyqtSignal(str)                     # routine_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._routines: List[RoutineDefinition] = []
        self._auto_timers: Dict[str, QTimer] = {}
        self._running: set[str] = set()                # routine IDs currently executing
        self._last_run: Dict[str, float] = {}          # routine_id → timestamp
        self._paused: bool = False

    # ── Loading ────────────────────────────────────────────────────

    def load(self, routines_dir: str | None = None):
        """Load (or reload) all routines from disk."""
        self.stop_auto_timers()
        self._routines = load_routines(routines_dir)
        self._start_auto_timers()
        log.info("RoutineManager: %d routine(s) loaded (%d auto, %d manual)",
                 len(self._routines),
                 sum(1 for r in self._routines if r.is_automatic),
                 sum(1 for r in self._routines if r.is_manual))

    @property
    def routines(self) -> List[RoutineDefinition]:
        return list(self._routines)

    # ── Scheduling ─────────────────────────────────────────────────

    def _start_auto_timers(self):
        """Create QTimers for all automatic routines."""
        for routine in self._routines:
            if not routine.is_automatic:
                continue
            interval_ms = routine.schedule.interval * 1000
            timer = QTimer(self)
            timer.setSingleShot(True)
            # Capture routine id for the lambda
            rid = routine.id
            timer.timeout.connect(lambda _rid=rid: self._on_auto_fire(_rid))
            timer.start(interval_ms)
            self._auto_timers[routine.id] = timer
            log.debug("AUTO_TIMER id=%s interval=%ds", routine.id, routine.schedule.interval)

    def _on_auto_fire(self, routine_id: str):
        """Fired by QTimer for an automatic routine."""
        routine = self._get_routine(routine_id)
        if routine is None:
            return
        if self._paused:
            # Re-schedule for later
            self._reschedule_auto(routine)
            return
        self._execute(routine)
        self._reschedule_auto(routine)

    def _reschedule_auto(self, routine: RoutineDefinition):
        """Restart the single-shot timer for an automatic routine."""
        timer = self._auto_timers.get(routine.id)
        if timer is None or not routine.is_automatic:
            return
        interval_ms = routine.schedule.interval * 1000
        timer.start(interval_ms)

    def stop_auto_timers(self):
        """Stop and clean up all automatic routine timers."""
        for timer in self._auto_timers.values():
            timer.stop()
        self._auto_timers.clear()

    def pause_all(self):
        """Pause automatic routine execution (e.g. gamer mode)."""
        self._paused = True
        for timer in self._auto_timers.values():
            timer.stop()

    def resume_all(self):
        """Resume automatic routine execution."""
        self._paused = False
        for routine in self._routines:
            if routine.is_automatic and routine.id in self._auto_timers:
                self._reschedule_auto(routine)

    # ── Trigger matching ───────────────────────────────────────────

    def try_match_keyword(self, question: str) -> Optional[RoutineDefinition]:
        """Check if *question* matches any manual routine's triggers.

        Returns the first matching routine or ``None``.
        """
        q_lower = question.lower()
        for routine in self._routines:
            if not routine.triggers:
                continue
            for trigger in routine.triggers:
                if trigger.lower() in q_lower:
                    log.info("ROUTINE_KEYWORD_MATCH id=%s trigger=%r",
                             routine.id, trigger)
                    return routine
        return None

    def get_routine_context_for_llm(self) -> str:
        """Build a description of manual routines for LLM intent classification.

        Used to inject routine awareness into the classify prompt.
        """
        manual = [r for r in self._routines if r.is_manual and r.triggers]
        if not manual:
            return ""
        lines = []
        for r in manual:
            triggers_str = ", ".join(r.triggers[:5])
            lines.append(f'- id="{r.id}" title="{r.title}" triggers=[{triggers_str}]')
        return "\n".join(lines)

    def get_routine_by_id(self, routine_id: str) -> Optional[RoutineDefinition]:
        """Look up a routine by ID."""
        return self._get_routine(routine_id)

    # ── Execution ──────────────────────────────────────────────────

    def run_routine(self, routine_id: str, variables: Optional[Dict[str, Any]] = None):
        """Public entry point — run a routine by ID in a background thread.

        Parameters
        ----------
        routine_id : str
            The unique routine identifier.
        variables : dict, optional
            Extra variables merged into the routine context before execution.
            Useful to pass a ``folder_path`` for the ``organize_folder`` routine.
        """
        routine = self._get_routine(routine_id)
        if routine is None:
            log.warning("Routine '%s' not found", routine_id)
            return
        if routine_id in self._running:
            log.debug("Routine '%s' already running, skipping", routine_id)
            return
        self._execute(routine, extra_vars=variables)

    def _execute(self, routine: RoutineDefinition, extra_vars: Optional[Dict[str, Any]] = None):
        """Spawn a thread to run the routine engine."""
        rid = routine.id
        self._running.add(rid)
        log.info("ROUTINE_EXEC id=%s title=%r", rid, routine.title)

        def _worker():
            try:
                result = run_routine(routine, extra_vars=extra_vars)
                self._last_run[rid] = time.time()
                self._running.discard(rid)
                self._deliver_result(result)
            except Exception as exc:
                self._running.discard(rid)
                log.error("ROUTINE_CRASH id=%s: %s", rid, exc, exc_info=True)
                self.routine_failed.emit(rid, str(exc))

        t = threading.Thread(target=_worker, name=f"routine-{rid}", daemon=True)
        t.start()

    def _deliver_result(self, result: RoutineResult):
        """Deliver the routine result via signals (thread-safe)."""
        if not result.success:
            self.routine_failed.emit(result.routine_id, result.error)
            return

        action = result.action
        if action is None:
            self.routine_done.emit(result.routine_id)
            return

        if action.type == "say":
            if action.llm or action.nollm:
                self.routine_say.emit(result.routine_id, action.llm or "", action.nollm or "")
            else:
                self.routine_done.emit(result.routine_id)
        elif action.type == "notification":
            title = result.context.get("routine_title", "Jacky")
            msg = action.message or action.nollm or action.llm
            self.routine_notify.emit(result.routine_id, title, msg)
        elif action.type == "log":
            msg = action.message or action.nollm or ""
            self.routine_log.emit(result.routine_id, msg)
        elif action.type == "organize":
            files_json = result.context.get("file_list", "[]")
            confirm_msg = action.confirm_msg or ""
            target_folder = result.context.get("_target_folder", "")
            self.routine_organize.emit(result.routine_id, files_json, confirm_msg, target_folder)
        else:
            log.warning("Unknown action type '%s' in routine '%s'",
                        action.type, result.routine_id)
            self.routine_done.emit(result.routine_id)

    # ── Status ─────────────────────────────────────────────────────

    def list_routines(self) -> List[Tuple[RoutineDefinition, str]]:
        """Return all routines with a status string.

        Status is one of: ``"running"``, ``"last: HH:MM"``, ``"idle"``.
        """
        items: List[Tuple[RoutineDefinition, str]] = []
        for r in self._routines:
            if r.id in self._running:
                status = "running"
            elif r.id in self._last_run:
                ts = self._last_run[r.id]
                status = f"last: {time.strftime('%H:%M', time.localtime(ts))}"
            else:
                status = "idle"
            items.append((r, status))
        return items

    def is_running(self, routine_id: str) -> bool:
        return routine_id in self._running

    # ── Cleanup ────────────────────────────────────────────────────

    def stop(self):
        """Stop all timers and clean up."""
        self.stop_auto_timers()
        self._routines.clear()
        log.info("RoutineManager stopped")

    # ── Internal ───────────────────────────────────────────────────

    def _get_routine(self, routine_id: str) -> Optional[RoutineDefinition]:
        for r in self._routines:
            if r.id == routine_id:
                return r
        return None
