"""TimerIntentMixin — timer/reminder/alarm intent handling and fired callbacks."""

import logging

from core.pet import PetState
from core.timer_manager import _format_duration, _format_time, _parse_iso
from core.screen_interaction.intent_classifier import IntentResult
from speech.dialogue import get_line

log = logging.getLogger("pet_window")


class TimerIntentMixin:
    """Mixin handling timer/reminder/alarm creation and fired-event speech."""

    # ── Fired event ───────────────────────────────────────────────────────────

    def _on_timer_fired(self, kind: str, label: str, entry_id: str, extra: str):
        """Called when a timer/reminder/alarm fires — show speech bubble + HAPPY animation."""
        trigger = f"{kind}_fired"
        kwargs = {"label": label or "Timer", "duration": extra, "time": extra}
        line = get_line(trigger, self.pet.name, **kwargs)
        if not line:
            line = f"⏰ {label or 'Timer!'}"
        log.info("TIMER_FIRED kind=%s label=%r extra=%r", kind, label, extra)
        self.pet.set_state(PetState.HAPPY)
        self._temp_state_timer.start(3000)
        self._say(line, force=True)

    # ── Intent processing ─────────────────────────────────────────────────────

    def _handle_timer_intent(self, result: IntentResult):
        """Process a classified timer intent from the LLM."""
        from datetime import datetime, time as dt_time

        kind = result.timer_kind or "timer"
        label = result.timer_label

        if kind == "timer":
            seconds = result.timer_seconds
            if seconds <= 0:
                self._say_forced(get_line("timer_none_active", self.pet.name))
                return
            entry = self._timer_manager.create_timer(seconds, label)
            if entry is None:
                self._say_forced(get_line("timer_limit_reached", self.pet.name, max=20))
                return
            duration_str = _format_duration(seconds, spoken=True)
            ack = get_line("timer_ack", self.pet.name, duration=duration_str)
            self._say_forced(ack)

        elif kind == "reminder":
            if result.timer_seconds > 0:
                entry = self._timer_manager.create_timer(result.timer_seconds, label)
                if entry is None:
                    self._say_forced(get_line("timer_limit_reached", self.pet.name, max=20))
                    return
                duration_str = _format_duration(result.timer_seconds, spoken=True)
                ack = (get_line("reminder_duration_ack", self.pet.name,
                                duration=duration_str, label=label)
                       or get_line("timer_ack", self.pet.name, duration=duration_str))
                self._say_forced(ack)
                return
            time_str = result.timer_time
            date_str = result.timer_date
            if not time_str:
                self._say_forced(get_line("timer_none_active", self.pet.name))
                return
            try:
                parts = time_str.split(":")
                hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
                target_time = dt_time(hour, minute)
            except (ValueError, IndexError):
                self._say_forced(get_line("timer_none_active", self.pet.name))
                return
            if date_str:
                try:
                    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    target_date = datetime.now().date()
            else:
                target_date = datetime.now().date()
            fire_dt = datetime.combine(target_date, target_time)
            entry = self._timer_manager.create_reminder(fire_dt, label)
            if entry is None:
                self._say_forced(get_line("timer_limit_reached", self.pet.name, max=20))
                return
            fire_parsed = _parse_iso(entry.fire_at)
            time_display = _format_time(fire_parsed) if fire_parsed else time_str
            ack = get_line("reminder_ack", self.pet.name, time=time_display, label=label)
            self._say_forced(ack)

        elif kind == "alarm":
            if result.timer_seconds > 0:
                entry = self._timer_manager.create_timer(result.timer_seconds, label)
                if entry is None:
                    self._say_forced(get_line("timer_limit_reached", self.pet.name, max=20))
                    return
                duration_str = _format_duration(result.timer_seconds, spoken=True)
                ack = get_line("timer_ack", self.pet.name, duration=duration_str)
                self._say_forced(ack)
                return
            time_str = result.timer_time
            if not time_str:
                self._say_forced(get_line("timer_none_active", self.pet.name))
                return
            try:
                parts = time_str.split(":")
                hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
                target_time = dt_time(hour, minute)
            except (ValueError, IndexError):
                self._say_forced(get_line("timer_none_active", self.pet.name))
                return
            repeat = result.timer_repeat or "none"
            entry = self._timer_manager.create_alarm(target_time, label, repeat)
            if entry is None:
                self._say_forced(get_line("timer_limit_reached", self.pet.name, max=20))
                return
            fire_parsed = _parse_iso(entry.fire_at)
            time_display = _format_time(fire_parsed) if fire_parsed else time_str
            ack = get_line("alarm_ack", self.pet.name, time=time_display)
            self._say_forced(ack)
