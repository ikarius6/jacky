"""MediaScanner — platform-abstracted media detection and control.

Uses winsdk on Windows to query the system-wide media transport controls.
Returns a no-op stub on macOS (future work).
"""

import asyncio
import logging
import sys
import threading
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class MediaInfo:
    """Snapshot of the currently playing media session."""
    title: str
    artist: str
    is_playing: bool  # True = playing, False = paused/stopped


class MediaScanner:
    """Async wrapper around OS media transport controls.

    All public methods are synchronous and safe to call from any thread.
    Internally they dispatch to a dedicated asyncio event-loop thread so they
    never block the Qt event loop.
    """

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._available = False
        self._setup()

    # ── Setup ──────────────────────────────────────────────────────────────────

    def _setup(self):
        if sys.platform != "win32":
            log.info("MediaScanner: not on Windows — media detection disabled")
            return
        try:
            from winsdk.windows.media.control import (  # noqa: F401
                GlobalSystemMediaTransportControlsSessionManager,
            )
            self._available = True
        except Exception as exc:
            log.warning("MediaScanner: winsdk not available — %s", exc)
            return
        # Spin up a dedicated asyncio event-loop thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="jacky-media-loop"
        )
        self._thread.start()

    @property
    def available(self) -> bool:
        return self._available

    # ── Public API (blocking, thread-safe) ─────────────────────────────────────

    def get_current_media(self) -> Optional[MediaInfo]:
        """Return current media info, or None if no active session."""
        if not self._available:
            return None
        return self._run(self._async_get_current_media())

    def play_pause(self) -> bool:
        if not self._available:
            return False
        return self._run(self._async_play_pause())

    def next_track(self) -> bool:
        if not self._available:
            return False
        return self._run(self._async_next_track())

    def previous_track(self) -> bool:
        if not self._available:
            return False
        return self._run(self._async_previous_track())

    # ── Async implementations (Windows / winsdk) ───────────────────────────────

    async def _async_get_current_media(self) -> Optional[MediaInfo]:
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as SM,
                GlobalSystemMediaTransportControlsSessionPlaybackStatus as PS,
            )
            manager = await SM.request_async()
            session = manager.get_current_session()
            if session is None:
                return None
            props = await session.try_get_media_properties_async()
            playback = session.get_playback_info()
            is_playing = (playback.playback_status == PS.PLAYING)
            return MediaInfo(
                title=props.title or "",
                artist=props.artist or "",
                is_playing=is_playing,
            )
        except Exception as exc:
            log.debug("MediaScanner: get_current_media error — %s", exc)
            return None

    async def _async_play_pause(self) -> bool:
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as SM,
            )
            manager = await SM.request_async()
            session = manager.get_current_session()
            if session is None:
                return False
            return await session.try_toggle_play_pause_async()
        except Exception as exc:
            log.debug("MediaScanner: play_pause error — %s", exc)
            return False

    async def _async_next_track(self) -> bool:
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as SM,
            )
            manager = await SM.request_async()
            session = manager.get_current_session()
            if session is None:
                return False
            return await session.try_skip_next_async()
        except Exception as exc:
            log.debug("MediaScanner: next_track error — %s", exc)
            return False

    async def _async_previous_track(self) -> bool:
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as SM,
            )
            manager = await SM.request_async()
            session = manager.get_current_session()
            if session is None:
                return False
            return await session.try_skip_previous_async()
        except Exception as exc:
            log.debug("MediaScanner: previous_track error — %s", exc)
            return False

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _run(self, coro):
        """Submit a coroutine to the dedicated loop and wait for the result."""
        if self._loop is None or self._loop.is_closed():
            return None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=5)
        except Exception as exc:
            log.debug("MediaScanner: _run error — %s", exc)
            return None
