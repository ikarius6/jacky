"""Timer, reminder, and alarm manager for Jacky desktop pet.

Manages countdown timers, time-based reminders, and alarms (with optional
daily repeat).  Entries persist to ``timers.json`` next to the config file
and are restored on startup.
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, time as dt_time
from typing import List, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from utils.paths import get_config_dir

log = logging.getLogger("timer_manager")

_TIMERS_FILE = os.path.join(get_config_dir(), "timers.json")
_MAX_ENTRIES = 20
_CHECK_INTERVAL_MS = 1_000   # 1 second
_MISSED_GRACE_S = 600  # fire missed one-shot entries up to 10 min old


@dataclass
class TimerEntry:
    """A single timer / reminder / alarm entry."""
    id: str                 # uuid4 hex
    kind: str               # "timer" | "reminder" | "alarm"
    label: str              # human label (empty for simple timers)
    fire_at: str            # ISO 8601 datetime (local) of next fire time
    created_at: str         # ISO 8601
    repeat: str             # "none" | "daily"
    original_seconds: int   # only for kind="timer" — countdown duration for display


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_iso(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _format_duration(seconds: int, spoken: bool = False) -> str:
    """Human-readable duration string like '5 min', '1h 30min', '45s'.

    When *spoken* is True the abbreviations are replaced with full
    translated words from the i18n system so that TTS engines pronounce
    the duration naturally (e.g. "30 segundos" instead of "30s").
    """
    if spoken:
        from utils.i18n import t
        def _unit(key_singular: str, key_plural: str, n: int) -> str:
            return t(key_plural) if n != 1 else t(key_singular)

        h = seconds // 3600
        remaining = seconds % 3600
        m = remaining // 60
        s = remaining % 60

        parts: list[str] = []
        if h:
            parts.append(f"{h} {_unit('ui.timer_hour_spoken', 'ui.timer_hours_spoken', h)}")
        if m:
            parts.append(f"{m} {_unit('ui.timer_minute_spoken', 'ui.timer_minutes_spoken', m)}")
        if s or not parts:
            parts.append(f"{s} {_unit('ui.timer_second_spoken', 'ui.timer_seconds_spoken', s)}")
        return " ".join(parts)

    # Abbreviated form for text bubbles / UI
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    remaining_s = seconds % 60
    if minutes < 60:
        if remaining_s:
            return f"{minutes}min {remaining_s}s"
        return f"{minutes} min"
    hours = minutes // 60
    remaining_m = minutes % 60
    if remaining_m:
        return f"{hours}h {remaining_m}min"
    return f"{hours}h"


def _format_time(dt: datetime) -> str:
    """Format a datetime as HH:MM for display."""
    return dt.strftime("%H:%M")


class TimerManager(QObject):
    """Manages timers, reminders, and alarms with persistence."""

    timer_fired = pyqtSignal(str, str, str, str)  # kind, label, entry_id, extra

    def __init__(self, pet_window):
        super().__init__(pet_window)
        self._pet = pet_window
        self._entries: List[TimerEntry] = []

        self._load()

        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self._check_tick)
        self._check_timer.start(_CHECK_INTERVAL_MS)

    # ── Public API ────────────────────────────────────────────────

    def create_timer(self, seconds: int, label: str = "") -> Optional[TimerEntry]:
        """Create a countdown timer that fires after *seconds*."""
        if len(self._entries) >= _MAX_ENTRIES:
            log.warning("Timer limit reached (%d)", _MAX_ENTRIES)
            return None
        if seconds <= 0:
            return None
        fire_at = datetime.now() + timedelta(seconds=seconds)
        entry = TimerEntry(
            id=uuid.uuid4().hex[:12],
            kind="timer",
            label=label,
            fire_at=fire_at.isoformat(timespec="seconds"),
            created_at=_now_iso(),
            repeat="none",
            original_seconds=seconds,
        )
        self._entries.append(entry)
        self._save()
        log.info("TIMER_CREATE id=%s seconds=%d label=%r fire_at=%s",
                 entry.id, seconds, label, entry.fire_at)
        return entry

    def create_reminder(self, fire_at_dt: datetime, label: str) -> Optional[TimerEntry]:
        """Create a reminder that fires at *fire_at_dt* with a message."""
        if len(self._entries) >= _MAX_ENTRIES:
            log.warning("Timer limit reached (%d)", _MAX_ENTRIES)
            return None
        if fire_at_dt <= datetime.now():
            # If time already passed today, assume tomorrow
            fire_at_dt += timedelta(days=1)
        entry = TimerEntry(
            id=uuid.uuid4().hex[:12],
            kind="reminder",
            label=label or "",
            fire_at=fire_at_dt.isoformat(timespec="seconds"),
            created_at=_now_iso(),
            repeat="none",
            original_seconds=0,
        )
        self._entries.append(entry)
        self._save()
        log.info("REMINDER_CREATE id=%s fire_at=%s label=%r",
                 entry.id, entry.fire_at, label)
        return entry

    def create_alarm(self, time_of_day: dt_time, label: str = "",
                     repeat: str = "daily") -> Optional[TimerEntry]:
        """Create an alarm at *time_of_day*, optionally repeating daily."""
        if len(self._entries) >= _MAX_ENTRIES:
            log.warning("Timer limit reached (%d)", _MAX_ENTRIES)
            return None
        fire_at_dt = datetime.combine(datetime.now().date(), time_of_day)
        if fire_at_dt <= datetime.now():
            fire_at_dt += timedelta(days=1)
        entry = TimerEntry(
            id=uuid.uuid4().hex[:12],
            kind="alarm",
            label=label or "",
            fire_at=fire_at_dt.isoformat(timespec="seconds"),
            created_at=_now_iso(),
            repeat=repeat if repeat in ("none", "daily") else "none",
            original_seconds=0,
        )
        self._entries.append(entry)
        self._save()
        log.info("ALARM_CREATE id=%s fire_at=%s repeat=%s label=%r",
                 entry.id, entry.fire_at, entry.repeat, label)
        return entry

    def cancel(self, entry_id: str) -> bool:
        """Cancel and remove an entry by ID. Returns True if found."""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.id != entry_id]
        if len(self._entries) < before:
            self._save()
            log.info("TIMER_CANCEL id=%s", entry_id)
            return True
        return False

    def list_active(self) -> List[TimerEntry]:
        """Return all active entries, sorted by fire time."""
        return sorted(self._entries, key=lambda e: e.fire_at)

    def stop(self):
        """Clean shutdown — stop the check timer."""
        self._check_timer.stop()

    # ── Check tick ────────────────────────────────────────────────

    def _check_tick(self):
        """Called every 15s — fire any entries whose time has come."""
        now = datetime.now()
        to_fire: List[TimerEntry] = []
        remaining: List[TimerEntry] = []

        for entry in self._entries:
            fire_dt = _parse_iso(entry.fire_at)
            if fire_dt is None:
                log.warning("Bad fire_at for entry %s: %r — discarding", entry.id, entry.fire_at)
                continue
            if now >= fire_dt:
                to_fire.append(entry)
            else:
                remaining.append(entry)

        if not to_fire:
            return

        for entry in to_fire:
            self._fire(entry)
            # Reschedule daily alarms
            if entry.kind == "alarm" and entry.repeat == "daily":
                fire_dt = _parse_iso(entry.fire_at)
                if fire_dt:
                    next_fire = fire_dt + timedelta(days=1)
                    # Advance past now in case multiple days were missed
                    while next_fire <= now:
                        next_fire += timedelta(days=1)
                    entry.fire_at = next_fire.isoformat(timespec="seconds")
                    remaining.append(entry)
                    log.info("ALARM_RESCHEDULE id=%s next=%s", entry.id, entry.fire_at)

        self._entries = remaining
        self._save()

    def _fire(self, entry: TimerEntry):
        """Emit the timer_fired signal with contextual info."""
        extra = ""
        if entry.kind == "timer":
            extra = _format_duration(entry.original_seconds, spoken=True)
        elif entry.kind in ("reminder", "alarm"):
            fire_dt = _parse_iso(entry.fire_at)
            if fire_dt:
                extra = _format_time(fire_dt)
            else:
                extra = ""
        log.info("TIMER_FIRE id=%s kind=%s label=%r extra=%r",
                 entry.id, entry.kind, entry.label, extra)
        self.timer_fired.emit(entry.kind, entry.label, entry.id, extra)

    # ── Persistence ───────────────────────────────────────────────

    def _save(self):
        """Write current entries to disk."""
        data = [asdict(e) for e in self._entries]
        try:
            with open(_TIMERS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError as exc:
            log.error("Failed to save timers: %s", exc)

    def _load(self):
        """Load entries from disk and run startup catch-up."""
        if not os.path.isfile(_TIMERS_FILE):
            return
        try:
            with open(_TIMERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            log.error("Failed to load timers: %s", exc)
            return
        if not isinstance(data, list):
            return

        entries: List[TimerEntry] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                entry = TimerEntry(
                    id=str(item.get("id", uuid.uuid4().hex[:12])),
                    kind=str(item.get("kind", "timer")),
                    label=str(item.get("label", "")),
                    fire_at=str(item.get("fire_at", "")),
                    created_at=str(item.get("created_at", "")),
                    repeat=str(item.get("repeat", "none")),
                    original_seconds=int(item.get("original_seconds", 0)),
                )
                entries.append(entry)
            except (TypeError, ValueError) as exc:
                log.warning("Skipping malformed timer entry: %s", exc)

        self._entries = entries
        self._on_startup_catchup()

    def _on_startup_catchup(self):
        """Handle entries that expired while the app was closed."""
        now = datetime.now()
        grace_cutoff = now - timedelta(seconds=_MISSED_GRACE_S)
        surviving: List[TimerEntry] = []

        for entry in self._entries:
            fire_dt = _parse_iso(entry.fire_at)
            if fire_dt is None:
                continue

            if fire_dt > now:
                # Not expired — keep as-is
                surviving.append(entry)
                continue

            # Entry expired while app was closed
            if entry.kind == "alarm" and entry.repeat == "daily":
                # Advance to next future occurrence
                next_fire = fire_dt
                while next_fire <= now:
                    next_fire += timedelta(days=1)
                entry.fire_at = next_fire.isoformat(timespec="seconds")
                surviving.append(entry)
                log.info("STARTUP_CATCHUP alarm_reschedule id=%s next=%s", entry.id, entry.fire_at)
            elif fire_dt >= grace_cutoff:
                # Missed by less than 10 min — fire immediately
                surviving.append(entry)
                log.info("STARTUP_CATCHUP fire_missed id=%s kind=%s", entry.id, entry.kind)
                # Will be picked up by the first _check_tick()
            else:
                # Too old — discard
                log.info("STARTUP_CATCHUP discard id=%s kind=%s fire_at=%s",
                         entry.id, entry.kind, entry.fire_at)

        self._entries = surviving
        self._save()
