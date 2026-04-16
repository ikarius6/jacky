"""Monitor Windows system events: battery status, power changes, and user idle time.

Uses polling via QTimer to avoid the complexity of hidden Win32 message windows.
Emits Qt signals that PetWindow can connect to for reactions.
"""

import logging
from enum import Enum, auto

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from pal import get_power_status as _pal_get_power_status, get_idle_seconds as _get_idle_seconds

log = logging.getLogger("system_events")


class SystemEvent(Enum):
    BATTERY_LOW = auto()          # Battery dropped below 20%
    BATTERY_CRITICAL = auto()     # Battery dropped below 10%
    BATTERY_CHARGING = auto()     # Power cable plugged in
    BATTERY_DISCHARGING = auto()  # Power cable unplugged
    BATTERY_FULL = auto()         # Battery reached 100% while charging
    USER_RETURNED = auto()        # User came back after being idle


def _get_power_status():
    """Return (ac_online: bool|None, percent: int|None)."""
    ac, pct = _pal_get_power_status()
    # Translate backend convention (-1 = unknown) to None for callers
    ac_out = None if not ac and pct == -1 else ac
    pct_out = None if pct == -1 else pct
    return ac_out, pct_out


# ── Monitor ──────────────────────────────────────────────────────

class SystemEventsMonitor(QObject):
    """Polls battery and user-idle status, emitting signals on transitions."""

    event_triggered = pyqtSignal(object, dict)  # (SystemEvent, extra_data)

    # Thresholds
    BATTERY_LOW_PCT = 20
    BATTERY_CRITICAL_PCT = 10
    IDLE_THRESHOLD_S = 300        # 5 minutes idle → user considered "away"

    # Cooldowns to avoid spamming
    _BATTERY_NOTIFY_COOLDOWN_S = 300   # 5 min between same-level battery alerts
    _USER_RETURN_COOLDOWN_S = 600      # 10 min between "welcome back" messages

    def __init__(self, parent=None):
        super().__init__(parent)

        # Battery tracking
        self._last_ac: bool | None = None
        self._last_pct: int | None = None
        self._notified_low = False
        self._notified_critical = False
        self._notified_full = False
        self._last_battery_notify_tick = 0.0

        # User idle tracking
        self._user_was_idle = False
        self._last_user_return_tick = 0.0

        # Poll timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    def start(self, poll_interval_ms: int = 30_000):
        """Begin polling. Call after the event loop is running."""
        # Seed initial state so the first poll doesn't fire spurious events
        ac, pct = _get_power_status()
        self._last_ac = ac
        self._last_pct = pct
        if pct is not None:
            self._notified_low = pct <= self.BATTERY_LOW_PCT
            self._notified_critical = pct <= self.BATTERY_CRITICAL_PCT
            self._notified_full = pct >= 100 and bool(ac)

        self._user_was_idle = _get_idle_seconds() >= self.IDLE_THRESHOLD_S

        log.info("SystemEventsMonitor started  ac=%s  pct=%s  idle=%.0fs",
                 ac, pct, _get_idle_seconds())
        self._timer.start(poll_interval_ms)

    def stop(self):
        self._timer.stop()

    # ── Polling ──────────────────────────────────────────────────

    def _poll(self):
        self._check_battery()
        self._check_user_idle()

    # ── Battery ──────────────────────────────────────────────────

    def _check_battery(self):
        ac, pct = _get_power_status()
        if ac is None and pct is None:
            return  # Desktop PC or unavailable — skip silently

        import time
        now = time.monotonic()

        # AC line transitions (plugged / unplugged)
        if self._last_ac is not None and ac is not None and ac != self._last_ac:
            if ac:
                self._emit(SystemEvent.BATTERY_CHARGING, pct=pct)
                # Reset low/critical notifications when plugged in
                self._notified_low = False
                self._notified_critical = False
                self._notified_full = False
            else:
                self._emit(SystemEvent.BATTERY_DISCHARGING, pct=pct)
        self._last_ac = ac

        if pct is None:
            return

        # Battery full while charging
        if ac and pct >= 100 and not self._notified_full:
            self._notified_full = True
            self._emit(SystemEvent.BATTERY_FULL, pct=pct)

        # Battery level thresholds (only while discharging)
        if not ac:
            cooldown_ok = (now - self._last_battery_notify_tick) >= self._BATTERY_NOTIFY_COOLDOWN_S

            if pct <= self.BATTERY_CRITICAL_PCT and not self._notified_critical and cooldown_ok:
                self._notified_critical = True
                self._last_battery_notify_tick = now
                self._emit(SystemEvent.BATTERY_CRITICAL, pct=pct)
            elif pct <= self.BATTERY_LOW_PCT and not self._notified_low and cooldown_ok:
                self._notified_low = True
                self._last_battery_notify_tick = now
                self._emit(SystemEvent.BATTERY_LOW, pct=pct)

        self._last_pct = pct

    # ── User idle ────────────────────────────────────────────────

    def _check_user_idle(self):
        idle_s = _get_idle_seconds()
        import time
        now = time.monotonic()

        if idle_s >= self.IDLE_THRESHOLD_S:
            self._user_was_idle = True
        elif self._user_was_idle:
            # User was idle and is now active → they "returned"
            self._user_was_idle = False
            if (now - self._last_user_return_tick) >= self._USER_RETURN_COOLDOWN_S:
                self._last_user_return_tick = now
                self._emit(SystemEvent.USER_RETURNED, idle_seconds=idle_s)

    # ── Helpers ──────────────────────────────────────────────────

    def _emit(self, event: SystemEvent, **data):
        log.info("SYSTEM_EVENT %s  data=%s", event.name, data)
        self.event_triggered.emit(event, data)
