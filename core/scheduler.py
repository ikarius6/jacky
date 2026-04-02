import logging
import random
from typing import Callable, Optional

from PyQt6.QtCore import QTimer

log = logging.getLogger("scheduler")


class Scheduler:
    """Timer-based scheduler that fires random pet events at configurable intervals."""

    def __init__(self):
        self._timers: dict[str, QTimer] = {}
        self._callbacks: dict[str, Callable] = {}

    def register(self, name: str, callback: Callable, interval_range: tuple[int, int]):
        """
        Register a named event that fires at random intervals.
        interval_range: (min_seconds, max_seconds).
        """
        self._callbacks[name] = callback
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._fire(name, interval_range))
        self._timers[name] = timer
        self._schedule_next(name, interval_range)

    def _schedule_next(self, name: str, interval_range: tuple[int, int]):
        """Schedule the next firing of a named event."""
        timer = self._timers.get(name)
        if timer is None:
            return
        delay_ms = random.randint(interval_range[0], interval_range[1]) * 1000
        log.debug("SCHEDULE '%s' in %ds", name, delay_ms // 1000)
        timer.start(delay_ms)

    def _fire(self, name: str, interval_range: tuple[int, int]):
        """Fire the callback and reschedule."""
        log.info("FIRE '%s'", name)
        cb = self._callbacks.get(name)
        if cb:
            cb()
        self._schedule_next(name, interval_range)

    def pause(self, name: str):
        """Pause a specific event timer."""
        timer = self._timers.get(name)
        if timer:
            timer.stop()

    def pause_all(self):
        """Pause all event timers."""
        for timer in self._timers.values():
            timer.stop()

    def resume(self, name: str, interval_range: tuple[int, int]):
        """Resume a specific event timer."""
        self._schedule_next(name, interval_range)

    def stop_all(self):
        """Stop and clean up all timers."""
        for timer in self._timers.values():
            timer.stop()
        self._timers.clear()
        self._callbacks.clear()
