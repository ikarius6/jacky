"""MusicMixin — music mode: song detection, walk/dance, mini player."""

import logging
import random
import threading

from PyQt6.QtCore import QTimer

from core.pet import PetState
from core.media_scanner import MediaScanner, MediaInfo
from utils.i18n import t

log = logging.getLogger("pet_window")

# Seconds between walk/dance actions while in music mode
_WALK_DANCE_MIN_S = 5
_WALK_DANCE_MAX_S = 10


class MusicMixin:
    """Mixin providing music mode: detect songs via winsdk, walk/dance, mini player."""

    # ── Initialization (called from PetWindow.__init__) ────────────────────────

    def _init_music(self):
        self._music_mode = False
        self._music_saved: dict | None = None
        self._music_scanner = MediaScanner()
        self._current_song: tuple[str, str] | None = None  # (title, artist)
        self._music_is_playing = False

        # Polling timer — checks current media every 3 s
        self._music_poll_timer = QTimer(self)
        self._music_poll_timer.setInterval(3000)
        self._music_poll_timer.timeout.connect(self._music_poll)

        # Walk/dance timer — triggers random movement every 5-10 s
        self._music_walk_timer = QTimer(self)
        self._music_walk_timer.setSingleShot(True)
        self._music_walk_timer.timeout.connect(self._music_walk_dance)

        # LLM comment delay timer
        self._music_llm_timer = QTimer(self)
        self._music_llm_timer.setSingleShot(True)
        self._music_llm_timer.timeout.connect(self._music_llm_comment)
        self._music_llm_song: tuple[str, str] | None = None  # song pending LLM

        # Wire the thread-safe signal
        self._music_info_ready.connect(self._on_music_info)

    # ── Mode toggle ────────────────────────────────────────────────────────────

    def toggle_music_mode(self, enabled: bool):
        """Toggle music mode — saves/restores settings like gamer mode."""
        if enabled and not self._music_mode:
            # Disable gamer mode if it's on (modes are exclusive)
            if self._gamer_mode:
                self.toggle_gamer_mode(False)
                self._context_menu._gamer_action.setChecked(False)

            self._music_saved = {
                "silent_mode": self._config.get("silent_mode", False),
                "window_push_enabled": self._config.get("window_push_enabled", True),
            }
            self._config["silent_mode"] = True
            self._config["window_push_enabled"] = False
            self._music_mode = True
            self._silent_mode = True
            self.reload_config()

            # Start timers
            self._music_poll_timer.start()
            self._schedule_music_walk()

            # Show player widget
            anchor_x = self.x() + self._sprite_size // 2
            anchor_y = self.y()
            self._music_player.show_at(anchor_x, anchor_y, pet_height=self._sprite_size)

            # Immediate poll
            self._music_poll()

            log.info("MUSIC_MODE enabled — saved %s", self._music_saved)

        elif not enabled and self._music_mode:
            # Stop timers
            self._music_poll_timer.stop()
            self._music_walk_timer.stop()
            self._music_llm_timer.stop()

            # Hide player
            self._music_player.hide()

            # Restore config
            if self._music_saved:
                for key, val in self._music_saved.items():
                    self._config[key] = val
                self._music_saved = None

            self._music_mode = False
            self._current_song = None
            self._music_is_playing = False
            self._music_llm_song = None

            import time
            self._last_user_interaction = time.monotonic()
            self.reload_config()
            self.pet.set_state(PetState.IDLE)
            log.info("MUSIC_MODE disabled — settings restored")

    # ── Polling ────────────────────────────────────────────────────────────────

    def _music_poll(self):
        """Poll the OS for current media info in a background thread."""
        if not self._music_mode:
            return
        threading.Thread(
            target=self._music_poll_bg, daemon=True, name="jacky-music-poll"
        ).start()

    def _music_poll_bg(self):
        """Background thread: fetch media info and emit signal."""
        info = self._music_scanner.get_current_media()
        self._music_info_ready.emit(info)

    def _on_music_info(self, info):
        """Handle media info on the main thread (connected via pyqtSignal)."""
        if not self._music_mode:
            return

        if info is None:
            # No active session
            if self._music_is_playing:
                self._music_is_playing = False
                self._music_player.update_play_state(False)
            return

        # Update play/pause state
        if info.is_playing != self._music_is_playing:
            self._music_is_playing = info.is_playing
            self._music_player.update_play_state(info.is_playing)

        # Detect song change
        new_song = (info.title, info.artist)
        if new_song != self._current_song and info.title:
            self._current_song = new_song
            self._on_song_changed(info.title, info.artist)

    def _on_song_changed(self, title: str, artist: str):
        """React to a song change — show bubble and optionally trigger LLM."""
        text = t("ui.music_now_playing", title=title, artist=artist)
        self._say(text, force=True, timeout_ms=5000, skip_voice=True)

        # Schedule LLM comment if enabled and permission granted
        if self._llm_enabled and not self._llm_pending and self._perm("allow_comment_music"):
            self._music_llm_song = (title, artist)
            self._music_llm_timer.start(2000)

    def _music_llm_comment(self):
        """Generate a witty LLM comment about the current song."""
        if not self._music_mode or not self._music_llm_song:
            return
        if self._llm_pending:
            return
        title, artist = self._music_llm_song
        self._music_llm_song = None
        prompt = t("llm_prompts.music_song_comment", title=title, artist=artist)
        if not prompt:
            return
        self._llm_pending = True
        context = self._build_llm_context(prompt)
        self._llm.generate(context, self._on_music_llm_response)

    def _on_music_llm_response(self, text: str | None):
        """Callback from LLM for song comment — thread-safe via signal."""
        self._llm_pending = False
        if text and self._music_mode:
            self._llm_ask_ready.emit(text)  # _ask_ready → _say_forced (bypasses silent)

    # ── Walk / Dance scheduling ────────────────────────────────────────────────

    def _schedule_music_walk(self):
        """Schedule the next walk/dance action."""
        if not self._music_mode:
            return
        delay_ms = random.randint(_WALK_DANCE_MIN_S, _WALK_DANCE_MAX_S) * 1000
        self._music_walk_timer.start(delay_ms)

    def _music_walk_dance(self):
        """Randomly walk or dance while in music mode."""
        if not self._music_mode:
            return
        if self.pet.state in (PetState.DRAGGED, PetState.FALLING):
            self._schedule_music_walk()
            return

        if random.random() < 0.5:
            # Walk to a random spot
            self.movement.pick_random_target()
            if random.random() < 0.3 and "run" in self.animation.available_states:
                self.pet.set_state(PetState.RUNNING)
            else:
                self.pet.set_state(PetState.WALKING)
        else:
            # Dance in place
            self.pet.set_state(PetState.DANCE)
            dance_duration = random.randint(3000, 5000)
            self._temp_state_timer.start(dance_duration)

        self._schedule_music_walk()

    # ── Media control methods (called from player widget) ──────────────────────

    def _music_play_pause(self):
        """Toggle play/pause on the current media session."""
        threading.Thread(
            target=self._music_control_bg, args=("play_pause",),
            daemon=True, name="jacky-music-ctrl"
        ).start()

    def _music_next(self):
        """Skip to next track."""
        threading.Thread(
            target=self._music_control_bg, args=("next",),
            daemon=True, name="jacky-music-ctrl"
        ).start()

    def _music_prev(self):
        """Skip to previous track."""
        threading.Thread(
            target=self._music_control_bg, args=("prev",),
            daemon=True, name="jacky-music-ctrl"
        ).start()

    def _music_control_bg(self, action: str):
        """Background thread: execute media control and poll immediately."""
        scanner = self._music_scanner
        if action == "play_pause":
            scanner.play_pause()
        elif action == "next":
            scanner.next_track()
        elif action == "prev":
            scanner.previous_track()
        # Brief delay to let the media app update, then poll
        import time
        time.sleep(0.3)
        info = scanner.get_current_media()
        self._music_info_ready.emit(info)
