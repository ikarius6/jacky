"""ConfigMixin — config permission helper, gamer mode, and runtime config reload."""

import logging

from PyQt6.QtCore import Qt

from core.character import get_character, get_sprites_dir
from core.animation import AnimationController
from interaction.context_menu import DEFAULT_PERMISSIONS, PERMISSION_DEFS
from utils.i18n import load_language, current_language
from speech.llm_provider import create_llm_provider
from core.screen_interaction.debug import set_enabled as _set_debug_enabled

log = logging.getLogger("pet_window")


class ConfigMixin:
    """Mixin providing permission checking, gamer mode, and live config reload."""

    # ── Permission helper ─────────────────────────────────────────────────────

    def _perm(self, key: str) -> bool:
        """Check a granular permission from config['permissions']."""
        perms = self._config.get("permissions", DEFAULT_PERMISSIONS)
        return perms.get(key, True)

    # ── Gamer mode ────────────────────────────────────────────────────────────

    def toggle_gamer_mode(self, enabled: bool):
        """Toggle gamer mode: suppress all distractions while gaming.

        On activation, saves current values of always_on_top, window_push_enabled,
        silent_mode, and gravity in memory, then disables everything (silent on).
        On deactivation, restores the saved values.
        """
        if enabled and not self._gamer_mode:
            self._gamer_saved = {
                "always_on_top": self._config.get("always_on_top", True),
                "window_push_enabled": self._config.get("window_push_enabled", True),
                "silent_mode": self._config.get("silent_mode", False),
                "gravity": self._config.get("gravity", False),
            }
            self._config["always_on_top"] = False
            self._config["window_push_enabled"] = False
            self._config["silent_mode"] = True
            self._config["gravity"] = False
            self._gamer_mode = True
            self._routine_manager.pause_all()
            self.reload_config()
            log.info("GAMER_MODE enabled — saved %s", self._gamer_saved)

        elif not enabled and self._gamer_mode:
            if self._gamer_saved:
                for key, val in self._gamer_saved.items():
                    self._config[key] = val
                self._gamer_saved = None
            self._gamer_mode = False
            import time
            self._last_user_interaction = time.monotonic()
            self._routine_manager.resume_all()
            self.reload_config()
            log.info("GAMER_MODE disabled — settings restored")

    # ── Config reload ─────────────────────────────────────────────────────────

    def reload_config(self):
        """Apply in-memory config after settings change (does not re-read from disk)."""
        self.pet.name = self._config.get("pet_name", "Jacky")
        self.movement._speed = self._config.get("movement_speed", 3)
        self.movement.set_gravity(self._config.get("gravity", False))
        self._llm_enabled = self._config.get("llm_enabled", False)
        self._silent_mode = self._config.get("silent_mode", False)

        new_lang = self._config.get("language", "es")
        if new_lang != current_language():
            load_language(new_lang)

        self._llm = create_llm_provider(self._config)

        # Apply always_on_top at runtime
        new_on_top = self._config.get("always_on_top", True)
        if new_on_top != self._always_on_top:
            self._always_on_top = new_on_top
            flags = (
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Tool
            )
            if self._always_on_top:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            self.setWindowFlags(flags)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setStyleSheet("background:transparent;")
            self.show()
            self._remove_dwm_border()
            if self._always_on_top:
                self._topmost_timer.start(5000)
                self._reassert_topmost()
            else:
                self._topmost_timer.stop()

        self._window_awareness.set_enabled(self._config.get("window_interaction_enabled", True))
        perms = self._config.get("permissions", DEFAULT_PERMISSIONS)
        any_destructive = any(
            perms.get(p[0], True)
            for p in PERMISSION_DEFS
            if p[3] == "destructive"
        )
        self._window_awareness.set_push_enabled(
            self._config.get("window_push_enabled", True) and any_destructive
        )
        self._context_menu.refresh_llm_state()

        new_shortcut = self._config.get("listen_shortcut", "ctrl+shift+space")
        self._global_hotkey.update_shortcut(new_shortcut)

        self._setup_scheduler()
        self._routine_manager.load()

        debug_on = self._config.get("debug_logging", False)
        root = logging.getLogger()
        root.setLevel(logging.DEBUG if debug_on else logging.WARNING)
        for h in root.handlers:
            h.setLevel(logging.DEBUG if debug_on else logging.WARNING)
        log.info("Logging level set to %s", "DEBUG" if debug_on else "WARNING")
        _set_debug_enabled(debug_on)

        # Hot-swap character if changed
        new_char = self._config.get("character", "Forest Ranger 3")
        if new_char != self._character_name:
            self._character_name = new_char
            self._char_cfg = get_character(new_char)
            sprites_dir = get_sprites_dir(new_char)
            self.animation.dispose()
            self.animation = AnimationController(
                sprites_dir,
                sprite_size=self._sprite_size,
                fps=self._char_cfg.get("fps", 6),
                layout=self._char_cfg.get("type", "flat"),
                state_map=self._char_cfg.get("state_map"),
            )
            self._anim_timer.setInterval(self.animation.frame_interval_ms)
            self._update_tray_icon()
