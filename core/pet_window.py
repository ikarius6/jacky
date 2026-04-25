import os
import sys
import logging
import random
import datetime
import time

from PyQt6.QtWidgets import QWidget, QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QIcon, QPixmap, QAction, QImage, QTransform, QColor

from core.pet import Pet, PetState, ANIMATION_FALLBACKS
from core.animation import AnimationController
from core.movement import MovementEngine
from core.character import get_character, get_sprites_dir
from core.scheduler import Scheduler
from core.system_events import SystemEventsMonitor, SystemEvent
from core.window_interactions import WindowInteractionHandler
from core.peer_interactions import PeerInteractionHandler
from core.screen_interaction import ScreenInteractionHandler
from core.screen_interaction.intent_classifier import classify_intent, IntentResult
from core.screen_interaction.constants import INTENT_CONFIDENCE_THRESHOLD
from core.timer_manager import TimerManager, _format_duration, _format_time, _parse_iso
from core.routines.manager import RoutineManager
from core.screen_interaction.debug import set_enabled as _set_debug_enabled
from interaction.click_handler import ClickHandler
from interaction.context_menu import PetContextMenu, DEFAULT_PERMISSIONS, PERMISSION_DEFS
from interaction.window_awareness import WindowAwareness
from interaction.peer_discovery import PeerDiscovery
from speech.bubble import SpeechBubble, ConfirmButtons
from speech.dialogue import get_line
from speech.llm_provider import create_llm_provider
from speech.voice import ElevenLabsTTSClient, AssemblyAISTTClient
from interaction.hotkey import GlobalHotkey
from utils.config_manager import load_config
from pal import remove_dwm_border, set_topmost
from utils.screen_capture import capture_vision_area
from utils.i18n import load_language, t, get_vision_keywords, get_confirm_words, get_easter_keywords, current_language

log = logging.getLogger("pet_window")

_REVERT_TAG = "\x00REVERT\x00"


class PetWindow(QWidget):
    """Main transparent frameless window that IS the pet."""

    _llm_text_ready = pyqtSignal(str)
    _llm_ask_ready = pyqtSignal(str)
    _intent_ready = pyqtSignal(object)  # IntentResult or None
    _organize_ready = pyqtSignal(str)   # LLM categorization JSON response
    _voice_transcript_ready = pyqtSignal(str)
    _voice_error_ready = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._config = load_config()
        load_language(self._config.get("language", "es"))
        self._sprite_size = self._config.get("sprite_size", 128)
        self._always_on_top = self._config.get("always_on_top", True)

        # Window setup — fully transparent, no border, no shadow
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
        self.setFixedSize(self._sprite_size, self._sprite_size)

        # Core components
        self.pet = Pet(name=self._config.get("pet_name", "Jacky"))
        self._character_name = self._config.get("character", "Forest Ranger 3")
        self._char_cfg = get_character(self._character_name)
        sprites_dir = get_sprites_dir(self._character_name)
        self.animation = AnimationController(
            sprites_dir,
            sprite_size=self._sprite_size,
            fps=self._char_cfg.get("fps", 6),
            layout=self._char_cfg.get("type", "flat"),
            state_map=self._char_cfg.get("state_map"),
        )
        self.movement = MovementEngine(
            sprite_size=self._sprite_size,
            speed=self._config.get("movement_speed", 3),
        )
        self.movement.set_gravity(self._config.get("gravity", False))
        self._apply_dpi_scale()
        self.scheduler = Scheduler()

        # LLM (must be initialized before context menu)
        self._llm = create_llm_provider(self._config)
        self._llm_enabled = self._config.get("llm_enabled", False)
        self._silent_mode = self._config.get("silent_mode", False)
        self._gamer_mode = False
        self._gamer_saved: dict | None = None
        self._llm_pending = False
        # Appearance easter egg mode: None | "evil" | "glitch"
        self._appearance_mode: str | None = None
        self._pending_question = ""  # stashed for intent classification callback
        self._pending_organize: dict | None = None  # stashed organize plan awaiting user confirmation
        self._llm_text_ready.connect(self._say)
        self._llm_ask_ready.connect(self._say_forced)
        self._organize_ready.connect(self._on_organize_llm_response)
        self._intent_ready.connect(self._on_intent_classified)

        # Interaction components
        self._click_handler = ClickHandler(self)
        self._context_menu = PetContextMenu(self)
        self._window_awareness = WindowAwareness(self)
        self._window_interactions = WindowInteractionHandler(self)
        self._peer_discovery = PeerDiscovery(self)
        self._peer_interactions = PeerInteractionHandler(self)
        self._screen_interaction = ScreenInteractionHandler(self)
        self._timer_manager = TimerManager(self)
        self._timer_manager.timer_fired.connect(self._on_timer_fired)
        self._routine_manager = RoutineManager(self)
        self._routine_manager.routine_say.connect(self._on_routine_say)
        self._routine_manager.routine_notify.connect(self._on_routine_notify)
        self._routine_manager.routine_log.connect(self._on_routine_log)
        self._routine_manager.routine_organize.connect(self._on_organize_proposal)
        self._routine_manager.routine_failed.connect(self._on_routine_failed)
        self._routine_manager.load()
        self._bubble = SpeechBubble()
        self._confirm_buttons = ConfirmButtons()
        self._confirm_buttons.confirmed.connect(self._on_confirm_button)

        # Voice and Hotkey
        self._tts_client = ElevenLabsTTSClient(
            api_key=self._config.get("elevenlabs_api_key", ""),
            voice_id=self._config.get("elevenlabs_voice_id", "U0W3edavfdI8ibPeeteQ"),
            model_id=self._config.get("elevenlabs_model", "eleven_flash_v2_5"),
            allow_cache_func=lambda: self._perm("allow_cache"),
        )
        self._stt_client = AssemblyAISTTClient(
            api_key=self._config.get("assemblyai_api_key", ""),
            model=self._config.get("assemblyai_model", "universal-streaming-multilingual")
        )
        # Use signals for thread-safe delivery from daemon STT thread to main GUI thread
        self._voice_transcript_ready.connect(self.on_ask)
        self._voice_error_ready.connect(lambda err: self._say(f"STT Error: {err}", force=True, skip_voice=True))
        self._stt_client.on_transcript_callback = self._voice_transcript_ready.emit
        self._stt_client.on_error_callback = self._voice_error_ready.emit
        self._listen_timeout = QTimer(self)
        self._listen_timeout.setSingleShot(True)
        self._listen_timeout.timeout.connect(self._on_listen_timeout)
        
        self._global_hotkey = GlobalHotkey(
            shortcut=self._config.get("listen_shortcut", "ctrl+shift+space")
        )
        self._global_hotkey.pressed.connect(self.on_listen_toggle)
        self._global_hotkey.start()

        # State tracking
        self._temp_state_timer = QTimer(self)
        self._temp_state_timer.setSingleShot(True)
        self._temp_state_timer.timeout.connect(self._end_temp_state)

        # Talk-to-idle timer (cancellable — replaces QTimer.singleShot)
        self._talk_end_timer = QTimer(self)
        self._talk_end_timer.setSingleShot(True)
        self._talk_end_timer.timeout.connect(self._end_talk_to_idle)

        # Fall safety: force-land if FALLING lasts too long
        self._fall_safety_timer = QTimer(self)
        self._fall_safety_timer.setSingleShot(True)
        self._fall_safety_timer.timeout.connect(self._force_land)

        # Barrel-roll easter egg: rapid L→R sprite flipping
        self._barrel_roll_timer = QTimer(self)
        self._barrel_roll_timer.setInterval(150)
        self._barrel_roll_timer.timeout.connect(self._barrel_roll_tick)
        self._barrel_roll_count = 0

        # Appearance easter egg: auto-revert timer (30 s)
        self._appearance_timer = QTimer(self)
        self._appearance_timer.setSingleShot(True)
        self._appearance_timer.timeout.connect(self._revert_appearance)

        # Glitch: rapid random-color tint shift every 80 ms
        self._glitch_color_r = 255
        self._glitch_color_g = 0
        self._glitch_color_b = 200
        self._glitch_tick_timer = QTimer(self)
        self._glitch_tick_timer.setInterval(80)
        self._glitch_tick_timer.timeout.connect(self._glitch_tick)

        # Boredom escalation (idle neglect easter egg)
        self._BOREDOM_CALLOUT_MIN = 10
        self._BOREDOM_ERRATIC_MIN = 20
        self._BOREDOM_SELFTALK_MIN = 30
        self._BOREDOM_ASLEEP_MIN = 60
        self._BOREDOM_SELFTALK_INTERVAL_S = 120  # self-talk every 2 min
        self._last_user_interaction: float = time.monotonic()
        self._boredom_level: int = 0       # 0=normal, 1=callout, 2=erratic, 3=selftalk, 4=asleep
        self._boredom_asleep: bool = False
        self._last_selftalk: float = 0.0
        self._boredom_timer = QTimer(self)
        self._boredom_timer.setInterval(60_000)  # check every 60s
        self._boredom_timer.timeout.connect(self._check_boredom)
        self._boredom_timer.start()

        # Animation timer
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._anim_timer.start(self.animation.frame_interval_ms)

        # Movement timer (~30 FPS)
        self._move_timer = QTimer(self)
        self._move_timer.timeout.connect(self._on_move_tick)
        self._move_timer.start(33)

        # Topmost reassertion timer — Windows can revoke the topmost flag
        self._topmost_timer = QTimer(self)
        self._topmost_timer.timeout.connect(self._reassert_topmost)
        if self._always_on_top:
            self._topmost_timer.start(5000)  # every 5 seconds

        # Throttle for _refresh_screen_bounds (avoid querying geometry every 33ms)
        self._BOUNDS_REFRESH_INTERVAL_S = 2.0
        self._last_bounds_refresh = 0.0
        self._bounds_dirty = True  # force first refresh
        self._connect_screen_signals()

        # Pet state change listener
        self.pet.on_state_change(self._on_state_change)

        # Setup scheduler events
        self._setup_scheduler()

        # Setup window awareness
        self._setup_window_awareness()

        # Setup peer discovery
        self._setup_peer_discovery()

        # System events (battery, idle, power)
        self._system_events = SystemEventsMonitor(self)
        self._setup_system_events()

        # System tray
        self._setup_tray()

        # Initial position: bottom center of screen
        self._init_position()

    def _perm(self, key: str) -> bool:
        """Check a granular permission from config['permissions']."""
        perms = self._config.get("permissions", DEFAULT_PERMISSIONS)
        return perms.get(key, True)

    def _apply_dpi_scale(self):
        """Pass the screen DPI scale to the movement engine for coord conversion.

        On macOS, CG window coordinates are already in logical points that
        match Qt coords, so no scaling is needed (scale stays 1.0).
        On Windows, GetWindowRect returns physical pixels that must be divided
        by devicePixelRatio.
        """
        from pal import backend
        if backend.coords_are_physical:
            screen = self._current_screen()
            if screen:
                self.movement.set_dpi_scale(screen.devicePixelRatio())
        else:
            self.movement.set_dpi_scale(1.0)

    def _init_position(self):
        self._refresh_screen_bounds()
        geo = self._screen_geo()
        x = geo.x() + geo.width() // 2 - self._sprite_size // 2
        y = geo.y() + geo.height() - self._sprite_size
        self.move(x, y)
        self.movement.set_position(x, y)
        log.info("INIT_POS (%d,%d) screen=%s", x, y, (geo.x(), geo.y(), geo.width(), geo.height()))

    def _current_screen(self):
        """Return the QScreen that contains the pet's center point."""
        center = QPoint(self.x() + self._sprite_size // 2,
                        self.y() + self._sprite_size // 2)
        screen = QApplication.screenAt(center)
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen

    def _screen_geo(self):
        """Return the available geometry of the screen Jacky is currently on."""
        screen = self._current_screen()
        if screen:
            return screen.availableGeometry()
        from PyQt6.QtCore import QRect
        return QRect(0, 0, 1920, 1080)

    def _virtual_desktop_geo(self):
        """Return the bounding rect of all screens' available geometries."""
        from PyQt6.QtCore import QRect
        screens = QApplication.screens()
        if not screens:
            return QRect(0, 0, 1920, 1080)
        result = screens[0].availableGeometry()
        for s in screens[1:]:
            result = result.united(s.availableGeometry())
        return result

    def _connect_screen_signals(self):
        """Listen for screen geometry changes to invalidate cached bounds."""
        for screen in QApplication.screens():
            screen.geometryChanged.connect(self._on_screen_geometry_changed)
            screen.availableGeometryChanged.connect(self._on_screen_geometry_changed)
        QApplication.instance().screenAdded.connect(self._on_screens_changed)
        QApplication.instance().screenRemoved.connect(self._on_screens_changed)

    def _on_screen_geometry_changed(self):
        self._bounds_dirty = True

    def _on_screens_changed(self, screen):
        self._bounds_dirty = True
        # Re-connect signals for the new screen list
        self._connect_screen_signals()

    def _refresh_screen_bounds(self):
        """Push virtual desktop bounds into the movement engine (multi-monitor)."""
        # Virtual desktop bounds for clamping — allows crossing screens
        vgeo = self._virtual_desktop_geo()
        self.movement.update_bounds(
            vgeo.x(), vgeo.y(),
            vgeo.x() + vgeo.width(),
            vgeo.y() + vgeo.height(),
        )
        # Current screen bounds for ground_y calculation
        geo = self._screen_geo()
        self.movement.update_current_screen(
            geo.x(), geo.y(),
            geo.x() + geo.width(),
            geo.y() + geo.height(),
        )
        # Per-screen rects for random target picking
        rects = []
        for s in QApplication.screens():
            g = s.availableGeometry()
            rects.append((g.x(), g.y(), g.x() + g.width(), g.y() + g.height()))
        self.movement.update_screen_rects(rects)
        self._last_bounds_refresh = time.monotonic()
        self._bounds_dirty = False

    def _maybe_refresh_screen_bounds(self):
        """Throttled screen-bounds refresh: updates at most every 2s, or immediately if dirty."""
        now = time.monotonic()
        if self._bounds_dirty or (now - self._last_bounds_refresh) >= self._BOUNDS_REFRESH_INTERVAL_S:
            self._refresh_screen_bounds()

    def _setup_scheduler(self):
        idle_range = tuple(self._config.get("idle_interval", [5, 15]))
        chat_range = tuple(self._config.get("chat_interval", [20, 60]))
        win_range = tuple(self._config.get("window_check_interval", [10, 30]))

        self.scheduler.register("walk", self._scheduled_walk, idle_range)
        self.scheduler.register("chat", self._scheduled_chat, chat_range)
        if self._config.get("window_interaction_enabled", True):
            self.scheduler.register("window_interact", self._window_interactions.scheduled_interact, win_range)
        if self._config.get("peer_interaction_enabled", True):
            peer_range = tuple(self._config.get("peer_check_interval", [8, 20]))
            self.scheduler.register("peer_interact", self._peer_interactions.scheduled_interact, peer_range)

    def _setup_system_events(self):
        """Wire up system event reactions (battery, power, user idle)."""
        self._system_events.event_triggered.connect(self._on_system_event)

    def _on_system_event(self, event: SystemEvent, data: dict):
        """React to a system-level event with speech (and optionally LLM)."""
        if event == SystemEvent.USER_RETURNED:
            self._touch_user_interaction()
        if self._silent_mode:
            return
        if self.pet.state == PetState.DRAGGED:
            return

        # Map event → dialogue trigger + extra format kwargs
        _EVENT_TRIGGERS = {
            SystemEvent.BATTERY_LOW:         "battery_low",
            SystemEvent.BATTERY_CRITICAL:    "battery_critical",
            SystemEvent.BATTERY_CHARGING:    "battery_charging",
            SystemEvent.BATTERY_DISCHARGING: "battery_discharging",
            SystemEvent.BATTERY_FULL:        "battery_full",
            SystemEvent.USER_RETURNED:       "user_returned",
        }
        trigger = _EVENT_TRIGGERS.get(event)
        if not trigger:
            return

        # Try LLM for a richer reaction, fall back to predefined lines
        if self._llm_enabled and not self._llm_pending:
            pct = data.get("pct", "?")
            _LLM_PROMPTS = {
                SystemEvent.BATTERY_LOW:
                    t("llm_prompts.sys_battery_low", pct=pct),
                SystemEvent.BATTERY_CRITICAL:
                    t("llm_prompts.sys_battery_critical", pct=pct),
                SystemEvent.BATTERY_CHARGING:
                    t("llm_prompts.sys_battery_charging"),
                SystemEvent.BATTERY_DISCHARGING:
                    t("llm_prompts.sys_battery_discharging"),
                SystemEvent.BATTERY_FULL:
                    t("llm_prompts.sys_battery_full"),
                SystemEvent.USER_RETURNED:
                    t("llm_prompts.sys_user_returned"),
            }
            prompt = _LLM_PROMPTS.get(event)
            if prompt:
                self._llm_pending = True
                ctx = self._build_llm_context(prompt)
                self._llm.generate(ctx, self._on_llm_response)
                return

        # Predefined line
        pct = data.get("pct", "")
        line = get_line(trigger, self.pet.name, pct=pct)
        if line:
            self._say(line)

    def _setup_peer_discovery(self):
        """Wire up peer discovery and peer interaction callbacks."""
        if not self._config.get("peer_interaction_enabled", True):
            return
        self._peer_discovery.on_peer_joined = self._peer_interactions.on_peer_joined
        self._peer_discovery.on_peer_left = self._peer_interactions.on_peer_left
        self._peer_discovery.on_event_received = self._peer_interactions.on_event_received

    def _setup_window_awareness(self):
        if not self._config.get("window_interaction_enabled", True):
            return
        perms = self._config.get("permissions", DEFAULT_PERMISSIONS)
        any_destructive = any(
            perms.get(p[0], True) for p in PERMISSION_DEFS if p[3] == "destructive"
        )
        self._window_awareness.set_push_enabled(
            self._config.get("window_push_enabled", True) and any_destructive
        )
        self._window_awareness.set_callbacks(
            on_opened=self._window_interactions.on_window_opened,
            on_closed=self._window_interactions.on_window_closed,
        )
        self._window_awareness.start(poll_interval_ms=3000)

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        self._update_tray_icon()
        self._tray.setToolTip(f"{self.pet.name} - Desktop Pet")

        tray_menu = QMenu()
        show_action = QAction(t("ui.tray_show", name=self.pet.name), tray_menu)
        show_action.triggered.connect(self._bring_to_front)
        tray_menu.addAction(show_action)

        settings_action = QAction(t("ui.tray_settings"), tray_menu)
        settings_action.triggered.connect(lambda: self._context_menu._open_settings())
        tray_menu.addAction(settings_action)

        tray_menu.addSeparator()
        quit_action = QAction(t("ui.tray_quit"), tray_menu)
        quit_action.triggered.connect(self.on_quit)
        tray_menu.addAction(quit_action)

        self._tray.setContextMenu(tray_menu)
        self._tray.show()

    def _update_tray_icon(self):
        """Set the tray icon to the character's first idle frame, scaled to 32x32."""
        idle_frame = self.animation.current_frame()
        if idle_frame and not idle_frame.isNull():
            icon_pm = idle_frame.scaled(
                32, 32,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            # Fallback: generic circle
            icon_pm = QPixmap(32, 32)
            icon_pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(icon_pm)
            p.setBrush(Qt.GlobalColor.cyan)
            p.drawEllipse(4, 4, 24, 24)
            p.end()
        self._tray.setIcon(QIcon(icon_pm))

    def _bring_to_front(self):
        self.show()
        self.raise_()
        self._reassert_topmost()

    def _reassert_topmost(self):
        """Re-assert HWND_TOPMOST via Win32 — guards against z-order demotion.

        On macOS we skip self.raise_() because it activates the app and steals
        focus from the user. The NSFloatingWindowLevel applied by set_topmost()
        is sufficient to keep the window above others without taking focus.
        """
        if not self._always_on_top:
            return
        try:
            # Only call raise_() on non-macOS; on macOS it steals focus.
            if sys.platform != "darwin":
                self.raise_()
            hwnd = int(self.winId())
            set_topmost(hwnd)
        except Exception:
            pass

    def set_click_through(self, click_through: bool):
        """Temporarily make the pet window and its speech bubble transparent to mouse clicks."""
        from pal import set_window_click_through
        set_window_click_through(int(self.winId()), click_through)
        if self._bubble:
            set_window_click_through(int(self._bubble.winId()), click_through)
        # Process events so Windows can update the exstyle immediately
        QApplication.processEvents()

    # --- Paint ---

    def paintEvent(self, event):
        frame = self.animation.current_frame()
        if frame is None:
            log.warning("PAINT frame=None anim_state='%s' pos=(%d,%d) visible=%s",
                        self.animation.current_state, self.x(), self.y(), self.isVisible())
            return

        # --- Appearance easter egg rendering ---
        if self._appearance_mode == "evil":
            img = frame.toImage().convertToFormat(QImage.Format.Format_ARGB32)
            img.invertPixels(QImage.InvertMode.InvertRgb)
            frame = QPixmap.fromImage(img)
        elif self._appearance_mode == "glitch":
            # Flip horizontally
            frame = frame.transformed(QTransform().scale(-1, 1))
            # Overlay a random-color tint
            tinted = QPixmap(frame.size())
            tinted.fill(Qt.GlobalColor.transparent)
            p = QPainter(tinted)
            p.drawPixmap(0, 0, frame)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
            p.fillRect(tinted.rect(),
                       QColor(self._glitch_color_r, self._glitch_color_g, self._glitch_color_b, 90))
            p.end()
            frame = tinted

        painter = QPainter(self)
        painter.drawPixmap(0, 0, frame)
        painter.end()

    # --- Mouse events ---

    def mousePressEvent(self, event):
        self._touch_user_interaction()
        self._click_handler.handle_press(event)

    def mouseMoveEvent(self, event):
        self._click_handler.handle_move(event)

    def mouseReleaseEvent(self, event):
        self._click_handler.handle_release(event)

    # --- Click handler callbacks ---

    def on_pet_clicked(self):
        """Left-click: pet reaction."""
        self._touch_user_interaction()
        if self._screen_interaction.is_active:
            self._screen_interaction.cancel()
            return
        log.info("ACTION on_pet_clicked pos=(%d,%d)", self.x(), self.y())
        self.pet.set_state(PetState.GETTING_PET)
        self._say(get_line("petted", self.pet.name))
        self._temp_state_timer.start(2000)

    def on_dizzy(self):
        """Easter egg: rapid clicks or long drag made Jacky dizzy."""
        if self.pet.state == PetState.HURT:
            return  # already dizzy
        log.info("EASTER_EGG dizzy meltdown pos=(%d,%d)", self.x(), self.y())
        self.pet.set_state(PetState.HURT)
        self._say(get_line("dizzy", self.pet.name))
        self._temp_state_timer.start(5000)
        QTimer.singleShot(5000, self._dizzy_recover)

    def _dizzy_recover(self):
        """Recovery line after dizzy meltdown."""
        line = get_line("dizzy_recover", self.pet.name)
        if line:
            self._say(line)

    # --- Easter eggs ---

    def _check_easter_egg(self, question: str) -> bool:
        """Match *question* against easter-egg trigger phrases.

        Returns True if an easter egg was triggered (caller should return early).
        """
        q_lower = question.lower().strip()
        easter_kw = get_easter_keywords()
        for egg_name, phrases in easter_kw.items():
            phrase_set = set(phrases)
            if self._match_words(q_lower, phrase_set):
                handler = getattr(self, f"_easter_{egg_name}", None)
                if handler:
                    log.info("EASTER_EGG %s triggered by '%s'", egg_name, question[:60])
                    handler()
                    return True
        return False

    def _easter_barrel_roll(self):
        """Barrel roll: rapid sprite flip L→R→L→R (6 flips, 150ms each)."""
        self._say(get_line("easter_barrel_roll", self.pet.name), force=True)
        self._barrel_roll_count = 0
        self._barrel_roll_timer.start()

    def _barrel_roll_tick(self):
        """One tick of the barrel-roll flip animation."""
        self._barrel_roll_count += 1
        self.pet.direction = -self.pet.direction
        if self._barrel_roll_count >= 8:
            self._barrel_roll_timer.stop()
            self._barrel_roll_count = 0

    def _easter_play_dead(self):
        """Play dead: DYING animation for 5s, then revive with a joke."""
        self._say(get_line("easter_play_dead", self.pet.name), force=True)
        self.pet.set_state(PetState.DYING)
        self._temp_state_timer.start(5000)
        QTimer.singleShot(5000, self._play_dead_revive)

    def _play_dead_revive(self):
        """Revive after playing dead."""
        line = get_line("easter_play_dead_revive", self.pet.name)
        if line:
            self._say(line, force=True)

    def _easter_dance(self):
        """Forced dance for 10 seconds."""
        self._say(get_line("easter_dance", self.pet.name), force=True)
        self.pet.set_state(PetState.DANCE)
        self._temp_state_timer.start(10000)

    def _easter_evil(self):
        """Evil mode: inverted color palette for 30 s. All dialogue lines end with 'muajaja~'."""
        log.info("EASTER_EGG evil mode activated")
        self._appearance_mode = "evil"
        self._glitch_tick_timer.stop()
        self._say(get_line("easter_evil", self.pet.name), force=True)
        self._appearance_timer.start(30_000)
        self.update()

    def _easter_glitch(self):
        """Glitch mode: flipped sprite + random color tint for 30 s. Dialogue is reversed."""
        log.info("EASTER_EGG glitch mode activated")
        self._appearance_mode = "glitch"
        self._glitch_tick_timer.start()
        self._say(get_line("easter_glitch", self.pet.name), force=True)
        self._appearance_timer.start(30_000)
        self.update()

    def _glitch_tick(self):
        """Randomise the glitch tint color each tick so it flickers."""
        self._glitch_color_r = random.randint(0, 255)
        self._glitch_color_g = random.randint(0, 255)
        self._glitch_color_b = random.randint(0, 255)
        self.update()

    def _revert_appearance(self):
        """Restore Jacky's normal appearance after the easter egg timer expires."""
        prev_mode = self._appearance_mode
        self._appearance_mode = None
        self._glitch_tick_timer.stop()
        self.update()
        if prev_mode == "evil":
            line = get_line("easter_evil_revert", self.pet.name)
        else:
            line = get_line("easter_glitch_revert", self.pet.name)
        if line:
            self._say(_REVERT_TAG + line, force=True)

    # --- Boredom escalation ---

    def _touch_user_interaction(self):
        """Record that the user just interacted with Jacky. Resets boredom and wakes if asleep."""
        self._last_user_interaction = time.monotonic()
        if self._boredom_asleep:
            self._wake_up()
        elif self._boredom_level > 0:
            log.info("BOREDOM reset (was level %d)", self._boredom_level)
            self._boredom_level = 0

    def _check_boredom(self):
        """Periodic check (every 60s) — escalate boredom if user hasn't interacted."""
        if self._gamer_mode or self._boredom_asleep:
            return
        elapsed_min = (time.monotonic() - self._last_user_interaction) / 60.0

        if elapsed_min >= self._BOREDOM_ASLEEP_MIN and self._boredom_level < 4:
            self._boredom_level = 4
            self._boredom_sleep()
        elif elapsed_min >= self._BOREDOM_SELFTALK_MIN and self._boredom_level < 3:
            self._boredom_level = 3
            self._say(get_line("bored_selftalk", self.pet.name))
            self.pet.set_state(PetState.IDLE)
            self._last_selftalk = time.monotonic()
        elif elapsed_min >= self._BOREDOM_SELFTALK_MIN and self._boredom_level == 3:
            # Already in self-talk stage — fire another monologue if interval elapsed
            now = time.monotonic()
            if (now - self._last_selftalk) >= self._BOREDOM_SELFTALK_INTERVAL_S:
                self._boredom_selftalk()
                self._last_selftalk = now
        elif elapsed_min >= self._BOREDOM_ERRATIC_MIN and self._boredom_level < 2:
            self._boredom_level = 2
            self._boredom_erratic_walk()
        elif elapsed_min >= self._BOREDOM_CALLOUT_MIN and self._boredom_level < 1:
            self._boredom_level = 1
            log.info("BOREDOM callout (%.1f min idle)", elapsed_min)
            self._say(get_line("bored_callout", self.pet.name))

    def _boredom_erratic_walk(self):
        """Boredom level 2: walk erratically with random direction changes."""
        log.info("BOREDOM erratic walk")
        self._say(get_line("bored_erratic", self.pet.name))
        self.movement.pick_random_target()
        self.pet.set_state(PetState.WALKING)
        # Schedule a few extra direction flips
        for i in range(3):
            QTimer.singleShot(2000 * (i + 1), self._boredom_erratic_step)

    def _boredom_erratic_step(self):
        """One step of erratic walking: pick a new random target and flip direction."""
        if self._boredom_level < 2 or self._boredom_asleep:
            return
        if self.pet.state not in (PetState.IDLE, PetState.WALKING):
            return
        self.pet.direction = -self.pet.direction
        self.movement.pick_random_target()
        if self.pet.state == PetState.IDLE:
            self.pet.set_state(PetState.WALKING)

    def _boredom_selftalk(self):
        """Boredom level 3: LLM self-talk monologue or predefined fallback."""
        if self._llm_enabled and not self._llm_pending:
            self._llm_pending = True
            context = self._build_llm_context(t("llm_prompts.idle_selftalk"))
            self._llm.generate(context, self._on_selftalk_response)
        else:
            self._say(get_line("bored_selftalk", self.pet.name))

    def _on_selftalk_response(self, text: str | None):
        """Callback from LLM for self-talk — thread-safe via signal."""
        self._llm_pending = False
        if text:
            self._llm_text_ready.emit(text)
        else:
            fallback = get_line("bored_selftalk", self.pet.name) or "..."
            self._llm_text_ready.emit(fallback)

    def _boredom_sleep(self):
        """Boredom level 4: fall asleep — DYING animation, pause scheduler."""
        log.info("BOREDOM asleep")
        self._boredom_asleep = True
        self._say(get_line("bored_asleep", self.pet.name))
        self.pet.set_state(PetState.DYING)
        self.scheduler.pause_all()

    def _wake_up(self):
        """Wake Jacky from boredom sleep — HAPPY animation, resume scheduler."""
        log.info("BOREDOM wakeup")
        self._boredom_asleep = False
        self._boredom_level = 0
        self.scheduler.resume_all()
        self.pet.set_state(PetState.HAPPY)
        self._temp_state_timer.start(3000)
        self._say(get_line("bored_wakeup", self.pet.name), force=True)

    def on_feed(self):
        """Feed from context menu."""
        self._touch_user_interaction()
        if self._screen_interaction.is_active:
            self._screen_interaction.cancel()
        log.info("ACTION on_feed pos=(%d,%d)", self.x(), self.y())
        self.pet.set_state(PetState.EATING)
        self._say(get_line("fed", self.pet.name))
        self._temp_state_timer.start(3000)

    def on_attack(self):
        """Attack from context menu: shooting if available, else slashing."""
        self._touch_user_interaction()
        if self._screen_interaction.is_active:
            self._screen_interaction.cancel()
        log.info("ACTION on_attack pos=(%d,%d)", self.x(), self.y())
        self.pet.set_state(PetState.ATTACKING)
        self._temp_state_timer.start(2000)

    def _needs_vision(self, text: str) -> bool:
        """Check if the user's question contains vision trigger words."""
        words = set(text.lower().split())
        return bool(words & get_vision_keywords())

    def _capture_vision(self) -> str:
        """Capture the 1024x1024 vision area centred on the pet and return base64 PNG."""
        cx = self.x() + self._sprite_size // 2
        cy = self.y() + self._sprite_size // 2
        screen = self._current_screen()
        dpi = screen.devicePixelRatio() if screen else 1.0
        return capture_vision_area(cx, cy, dpi_scale=dpi)

    def _move_to_screen_target(self, qt_x: int, qt_y: int):
        """Run the pet toward a screen-interaction target (Qt logical coords)."""
        # Offset so the pet's center lands on the target
        target_x = qt_x - self._sprite_size // 2
        target_y = qt_y - self._sprite_size // 2
        # Clamp to reachable screen bounds (click still uses unclamped task.target_coords)
        bounds = self.movement._get_bounds()
        target_x = max(bounds[0], min(target_x, bounds[2] - self._sprite_size))
        target_y = max(bounds[1], min(target_y, bounds[3] - self._sprite_size))
        self.movement._target_x = target_x
        self.movement._target_y = target_y
        self.movement._direction = 1 if target_x > self.movement._x else -1
        # Use RUNNING for speed; fall back to WALKING if run animation unavailable
        if "run" in self.animation.available_states:
            self.pet.set_state(PetState.RUNNING)
        else:
            self.pet.set_state(PetState.WALKING)

    def on_listen_toggle(self):
        """Toggle microphone recording for voice STT."""
        self._touch_user_interaction()
        if not self._config.get("assemblyai_api_key", "").strip():
            return

        if getattr(self._stt_client, "_is_recording", False):
            self._listen_timeout.stop()
            self._bubble.hide()
            self._stt_client.stop_listening()
        else:
            max_sec = self._config.get("listen_timeout_seconds", 60)
            self._say(t("ui.listening"), force=True, timeout_ms=max_sec * 1000, skip_voice=True)
            self._stt_client.start_listening()
            self._listen_timeout.start(max_sec * 1000)

    def _on_listen_timeout(self):
        """Auto-stop listening when the max recording duration expires."""
        if getattr(self._stt_client, "_is_recording", False):
            log.info("Listen timeout reached, auto-stopping STT")
            self._bubble.hide()
            self._stt_client.stop_listening()

    def _start_screen_task(self, action_type: str, target_desc: str,
                            type_text_content: str = None):
        """Validate permissions and start a screen interaction task."""
        if not self._perm("allow_vision"):
            self._say(t("ui.no_vision_perm"), force=True)
            return
        if action_type != "navigate" and not self._perm("allow_screen_interact"):
            self._say(t("ui.no_interact_perm"), force=True)
            return
        if self._screen_interaction.is_active:
            self._screen_interaction.cancel(say_line=False)
        if self._llm_pending:
            self._llm_pending = False
        self._screen_interaction.start_task(action_type, target_desc,
                                            type_text_content=type_text_content)

    def _ask_direct_or_vision(self, question: str):
        """Send the question to the LLM using vision or text based on keywords/permissions."""
        if self._needs_vision(question) and self._perm("allow_vision"):
            context = self._build_llm_context(t("llm_prompts.ask_vision", question=question))
            image_b64 = self._capture_vision()
            self._llm.generate_with_image(context, image_b64, self._on_ask_response)
        else:
            context = self._build_llm_context(t("llm_prompts.ask_direct", question=question))
            self._llm.generate(context, self._on_ask_response)

    def on_ask(self, question: str):
        """User asked a direct question via the Preguntar dialog.

        Flow:
        0. If there's a pending organize plan, check for yes/no confirmation
        1. Fast path — keyword matching (no LLM call)
        2. Fallback — LLM intent classification
        3. Based on LLM result → screen interaction, vision, or chat
        """
        self._touch_user_interaction()
        # ── Organize confirmation interception ──
        if self._pending_organize is not None:
            self._handle_organize_confirmation(question)
            return

        # ── Easter egg fast path ──
        easter_hit = self._check_easter_egg(question)
        if easter_hit:
            return

        if not self._llm_enabled:
            # Even without LLM, try running manual routines (nollm fallback)
            matched_routine = self._routine_manager.try_match_keyword(question)
            if matched_routine:
                self._routine_manager.run_routine(matched_routine.id)
            return

        # ── Fast path: routine keyword matching ──
        matched_routine = self._routine_manager.try_match_keyword(question)
        if matched_routine:
            self._show_thinking()
            self._routine_manager.run_routine(matched_routine.id)
            return

        # ── Fast path: screen interaction keyword matching ──
        parsed = self._screen_interaction.try_parse_interaction(question)
        if parsed:
            action_type, target_desc, type_text_content = parsed
            self._start_screen_task(action_type, target_desc,
                                    type_text_content=type_text_content)
            return

        if self._llm_pending:
            self._say(t("ui.busy"), force=True)
            return
        self._llm_pending = True
        self._pending_question = question
        self._show_thinking()

        # ── Fallback: LLM intent classification ──
        def _on_result(result):
            # Emit signal for thread-safe delivery to main thread
            self._intent_ready.emit(result)

        routine_ctx = self._routine_manager.get_routine_context_for_llm()
        classify_intent(question, self._llm, _on_result, routine_context=routine_ctx)

    def _on_intent_classified(self, result):
        """Handle the LLM intent classification result (runs on main thread via signal)."""
        question = self._pending_question
        self._pending_question = ""

        # If classification failed or is low confidence → fall through to chat
        if result is None or result.confidence < INTENT_CONFIDENCE_THRESHOLD:
            log.info("INTENT fallback to chat (result=%s)", result)
            self._ask_direct_or_vision(question)
            return

        log.info("INTENT classified: %s conf=%d target=%r",
                 result.intent, result.confidence, result.target)

        if result.is_interaction and result.target:
            # High-confidence interaction intent
            self._llm_pending = False
            self._bubble.hide()
            self._start_screen_task(result.intent, result.target,
                                    type_text_content=result.type_text or None)
        elif result.is_timer:
            # Timer/reminder/alarm intent
            self._llm_pending = False
            self._bubble.hide()
            self._handle_timer_intent(result)
        elif result.intent == "routine" and result.routine_id:
            # Routine intent — run the matched routine
            self._llm_pending = False
            routine = self._routine_manager.get_routine_by_id(result.routine_id)
            if routine:
                log.info("INTENT routine id=%s", result.routine_id)
                self._routine_manager.run_routine(routine.id)
            else:
                self._ask_direct_or_vision(question)
        elif result.intent == "vision":
            # Vision intent — use the vision flow with the original question
            if self._perm("allow_vision"):
                context = self._build_llm_context(t("llm_prompts.ask_vision", question=question))
                image_b64 = self._capture_vision()
                self._llm.generate_with_image(context, image_b64, self._on_ask_response)
            else:
                self._ask_direct_or_vision(question)
        else:
            # Chat or interaction without target → ask directly
            self._ask_direct_or_vision(question)

    def on_look(self):
        """Context-menu action: pet looks at the screen and comments on what it sees."""
        self._touch_user_interaction()
        if not self._llm_enabled:
            self._say(t("ui.no_llm"), force=True)
            return
        if not self._perm("allow_vision"):
            self._say(t("ui.no_vision_perm"), force=True)
            return
        if self._llm_pending:
            self._say(t("ui.busy"), force=True)
            return
        self._llm_pending = True
        self._show_thinking()
        context = self._build_llm_context(t("llm_prompts.action_look"))
        image_b64 = self._capture_vision()
        self._llm.generate_with_image(context, image_b64, self._on_ask_response)

    # --- Timer / Reminder / Alarm ----------------------------------------

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
            # Prefer relative duration when available — the LLM often
            # mis-converts "en 10 minutos" into a bogus timer_time like "00:10".
            if result.timer_seconds > 0:
                entry = self._timer_manager.create_timer(result.timer_seconds, label)
                if entry is None:
                    self._say_forced(get_line("timer_limit_reached", self.pet.name, max=20))
                    return
                duration_str = _format_duration(result.timer_seconds, spoken=True)
                ack = get_line("reminder_duration_ack", self.pet.name, duration=duration_str, label=label) \
                    or get_line("timer_ack", self.pet.name, duration=duration_str)
                self._say_forced(ack)
                return
            time_str = result.timer_time  # "HH:MM"
            date_str = result.timer_date  # "YYYY-MM-DD" or ""
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
            # Prefer relative duration when available (same rationale as reminder)
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

    def on_drag_start(self):
        """User started dragging."""
        if self._screen_interaction.is_active:
            self._screen_interaction.cancel()
        log.info("ACTION on_drag_start pos=(%d,%d)", self.x(), self.y())
        self.pet.set_state(PetState.DRAGGED)
        self.scheduler.pause_all()
        self.movement.stop()
        self._say(get_line("dragged", self.pet.name))

    def on_drag_end(self):
        """User stopped dragging."""
        pos = self.pos()
        log.info("ACTION on_drag_end pos=(%d,%d)", pos.x(), pos.y())
        # Refresh bounds & DPI — pet may have been dragged to a different monitor
        self._refresh_screen_bounds()
        self._apply_dpi_scale()
        self.movement.set_position_after_drop(pos.x(), pos.y())
        if self.movement.gravity_enabled and self.movement.is_airborne:
            self.pet.set_state(PetState.FALLING)
        else:
            self.pet.set_state(PetState.IDLE)
        self.scheduler.resume_all()  # resume paused timers, don't re-register

        # Easter egg: protest when dropped near a screen edge/corner
        self._check_corner_exile(pos.x(), pos.y())

    def _check_corner_exile(self, x: int, y: int):
        """Easter egg: protest if dropped within 20px of a screen edge/corner."""
        margin = 20
        geo = self._screen_geo()
        left = geo.x()
        top = geo.y()
        right = geo.x() + geo.width() - self._sprite_size
        bottom = geo.y() + geo.height() - self._sprite_size

        near_edge = (
            x - left <= margin
            or right - x <= margin
            or y - top <= margin
            or bottom - y <= margin
        )
        if near_edge:
            line = get_line("corner_exile", self.pet.name)
            if line:
                self._say(line)

    def show_context_menu(self, pos: QPoint):
        self._touch_user_interaction()
        self._context_menu.show_at(pos)

    def on_quit(self):
        """Graceful exit."""
        self._say(get_line("farewell", self.pet.name))
        QTimer.singleShot(2000, self._do_quit)

    def _do_quit(self):
        self.scheduler.stop_all()
        self._boredom_timer.stop()
        self._system_events.stop()
        self._peer_discovery.stop()
        self._window_awareness.stop()
        self._timer_manager.stop()
        self._routine_manager.stop()
        self._bubble.hide()
        self._tray.hide()
        QApplication.instance().quit()

    # --- Animation tick ---

    def _on_anim_tick(self):
        anim_name = self.pet.get_animation_name()
        # Resolve fallback if primary animation is not in the current sprite pack
        if anim_name not in self.animation.available_states:
            for alt in ANIMATION_FALLBACKS.get(anim_name, []):
                if alt in self.animation.available_states:
                    anim_name = alt
                    break
            else:
                log.warning("ANIM_MISS state='%s' not in available=%s pos=(%d,%d)",
                            anim_name, self.animation.available_states, self.x(), self.y())
        # Keep the controller aware of the current facing direction so every
        # animation (idle, talk, hurt, jump…) mirrors correctly when facing left.
        self.animation.set_facing(self.pet.direction < 0)
        self.animation.set_state(anim_name)
        self.animation.tick()
        self.update()

    # --- Movement tick ---

    def _on_move_tick(self):
        if self.pet.state != PetState.DRAGGED:
            # Keep screen bounds fresh (throttled — every ~2s or on geometry change)
            self._maybe_refresh_screen_bounds()

            if self.pet.state in (PetState.WALKING, PetState.RUNNING):
                if self._screen_interaction.is_active:
                    self.movement.speed_multiplier = 4.0  # fast traverse for interaction tasks
                elif self.pet.state == PetState.RUNNING:
                    self.movement.speed_multiplier = 2.0
                else:
                    self.movement.speed_multiplier = 1.0
                still_moving = self.movement.tick()
                self.move(self.movement.x, self.movement.y)
                self.pet.direction = self.movement.direction

                # Drag window along while walking
                if self._window_interactions.dragging_window_hwnd is not None:
                    self._window_awareness.drag_window_tick(
                        self._window_interactions.dragging_window_hwnd,
                        self.movement.x, self.movement.y,
                        self._sprite_size,
                    )

                if not still_moving:
                    self.movement.speed_multiplier = 1.0
                    self._window_interactions.dragging_window_hwnd = None
                    log.debug("WALK_DONE pos=(%d,%d)", self.x(), self.y())
                    if self._screen_interaction.is_active:
                        self._screen_interaction.on_arrival()
                    else:
                        self.pet.set_state(PetState.IDLE)

                # Check if walking toward a peer
                self._peer_interactions.check_peer_arrival()
            else:
                if self.movement.gravity_enabled:
                    self.movement.apply_gravity()
                    self.move(self.movement.x, self.movement.y)
                    _no_fall_states = (PetState.FALLING, PetState.DRAGGED, PetState.JUMPING)
                    if self.movement.is_airborne and self.pet.state not in _no_fall_states:
                        log.info("GRAVITY airborne detected state=%s pos=(%d,%d)",
                                 self.pet.state.name, self.x(), self.y())
                        self.pet.set_state(PetState.FALLING)
                        self._start_fall_safety()
                    elif self.pet.state == PetState.FALLING and not self.movement.is_airborne:
                        log.info("GRAVITY landed pos=(%d,%d)", self.x(), self.y())
                        self._cancel_fall_safety()
                        self.pet.set_state(PetState.IDLE)

        # Always keep bubble following the pet
        self._update_bubble_pos()

    # --- Scheduled events ---

    def _scheduled_walk(self):
        if self._boredom_asleep:
            return
        if self.pet.state not in (PetState.IDLE,):
            return
        log.info("SCHED walk from pos=(%d,%d)", self.x(), self.y())
        self.movement.pick_random_target()
        # 30% chance to run instead of walk (if character supports it)
        if random.random() < 0.3 and "run" in self.animation.available_states:
            self.pet.set_state(PetState.RUNNING)
        else:
            self.pet.set_state(PetState.WALKING)

    def _scheduled_chat(self):
        log.info("SCHED chat state=%s pos=(%d,%d)", self.pet.state.name, self.x(), self.y())
        if self._boredom_asleep:
            return
        if self._silent_mode:
            return
        if self.pet.state in (PetState.DRAGGED, PetState.TALKING):
            return

        # --- Witching hour easter egg (3 AM, 50% chance) ---
        hour = datetime.datetime.now().hour
        if hour == 3 and random.random() < 0.5:
            if random.random() < 0.7:
                self._say(get_line("witching_hour", self.pet.name))
            else:
                log.info("EASTER witching_hour possessed animation")
                self.pet.set_state(PetState.DYING)
                self._temp_state_timer.start(2500)
            return

        if self._llm_enabled:
            if self._llm_pending:
                log.debug("SCHED chat skipped — LLM request already pending")
                return
            self._llm_pending = True
            context = self._build_llm_context(t("llm_prompts.idle_chat"))
            self._llm.generate(context, self._on_llm_response)
        else:
            # 20% chance of late-night comment when it's late
            if (hour >= 23 or hour < 5) and random.random() < 0.2:
                self._say(get_line("late_night", self.pet.name))
            else:
                self._say(get_line("idle", self.pet.name))

    # --- Speech ---

    def _say(self, text: str | None, timeout_ms: int = 0, force: bool = False, skip_voice: bool = False):
        """Show a speech bubble with text.

        timeout_ms: override auto-calculated timeout (0 = auto).
        force: if True, ignore silent mode (used for direct user questions).
        skip_voice: if True, skips Text-to-Speech playback.
        """
        # --- Appearance easter egg text effects ---
        if text and text.startswith(_REVERT_TAG):
            text = text[len(_REVERT_TAG):]  # strip sentinel, no effect applied
        elif text and self._appearance_mode == "evil":
            if not text.rstrip().endswith("muajaja~") and not text.rstrip().endswith("muahaha~"):
                text = text.rstrip() + " muajaja~"
        elif text and self._appearance_mode == "glitch":
            text = text[::-1]

        if not text:
            return
        if self._pending_organize is not None:
            return
        if self._silent_mode and not force:
            return
            
        mode = self._config.get("response_mode", "both")
        if mode in ("voice", "both") and not skip_voice:
            self._tts_client.play_tts(text)
            if mode == "voice":
                self._bubble.hide()
                self.pet.set_state(PetState.TALKING)
                self._talk_end_timer.start(max(3000, len(text) * 50))
                return
                
        log.info("SAY state=%s pos=(%d,%d) text='%s'", self.pet.state.name, self.x(), self.y(), text[:80])
        old_state = self.pet.state
        _KEEP_ANIM = (PetState.HAPPY, PetState.EATING, PetState.DRAGGED,
                     PetState.ATTACKING, PetState.HURT,
                     PetState.DYING, PetState.WALKING, PetState.RUNNING,
                     PetState.DANCE, PetState.GETTING_PET)
        if old_state not in _KEEP_ANIM:
            self.pet.set_state(PetState.TALKING)

        anchor_x = self.x() + self._sprite_size // 2
        anchor_y = self.y()
        if timeout_ms <= 0:
            min_timeout = self._config.get("bubble_timeout", 5) * 1000
            word_count = len(text.split())
            timeout_ms = max(min_timeout, int(word_count * 400))
        self._bubble.show_message(text, anchor_x, anchor_y, timeout_ms=timeout_ms,
                                  pet_height=self._sprite_size)
        
        # When bubble is shown, bring pet to the exact same top z-order
        self._reassert_topmost()

        # Return to IDLE after bubble hides — never restore transient states
        # that could leave the pet stuck (PEEKING, FALLING, INTERACTING, etc.)
        # Uses _talk_end_timer so a new _say() cancels any pending timer.
        if old_state not in _KEEP_ANIM:
            self._talk_end_timer.start(timeout_ms)

    def _say_forced(self, text: str | None):
        """Show speech bubble ignoring silent mode (for direct user questions)."""
        self._say(text, force=True)

    def _end_talk_to_idle(self):
        if self.pet.state == PetState.TALKING:
            log.debug("END_TALK -> IDLE pos=(%d,%d)", self.x(), self.y())
            self.pet.set_state(PetState.IDLE)

    def _show_thinking(self):
        """Show animated thinking indicator in the speech bubble."""
        self.pet.set_state(PetState.TALKING)
        anchor_x = self.x() + self._sprite_size // 2
        anchor_y = self.y()
        self._bubble.show_thinking(anchor_x, anchor_y, pet_height=self._sprite_size)
        self._reassert_topmost()

    def _update_bubble_pos(self):
        anchor_x = self.x() + self._sprite_size // 2
        anchor_y = self.y()
        if self._bubble.isVisible():
            self._bubble.update_position(anchor_x, anchor_y)
        if self._confirm_buttons.isVisible():
            self._confirm_buttons.update_position(anchor_x, anchor_y)

    # --- LLM ---

    def _build_llm_context(self, situation: str) -> str:
        parts = [f"Situation: {situation}"]
        # Pick ONE random interesting window instead of listing all
        interesting = self._window_awareness.get_interesting_windows()
        if interesting:
            pick = random.choice(interesting)
            parts.append(f"Foreground app: {pick.title}")
        # Only mention time if it's notably late or early
        hour = datetime.datetime.now().hour
        if hour >= 23 or hour < 5:
            parts.append(f"Current time: {datetime.datetime.now().strftime('%H:%M')}")
        return " | ".join(parts)

    def _on_llm_response(self, text: str | None):
        """Callback from LLM thread — emit signal for thread-safe delivery."""
        self._llm_pending = False
        if text:
            self._llm_text_ready.emit(text)
        else:
            # Fallback to predefined
            fallback = get_line("idle", self.pet.name) or "..."
            self._llm_text_ready.emit(fallback)

    def _on_ask_response(self, text: str | None):
        """Callback from LLM for user questions — shows error on failure."""
        self._llm_pending = False
        if text:
            self._llm_ask_ready.emit(text)
        else:
            self._llm_ask_ready.emit(t("ui.llm_error"))

    # --- Routines ---

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

    # --- Desktop organize ---

    _AFFIRM_FALLBACK = {"yes", "ok", "sure", "sí", "si", "dale", "adelante"}
    _DENY_FALLBACK = {"no", "nope", "cancel", "cancela"}

    @staticmethod
    def _match_words(q_lower: str, word_set: set[str]) -> bool:
        """Check if *q_lower* matches any word/phrase in *word_set*.

        Single words are matched against individual tokens (split); multi-word
        phrases are matched as substrings.
        """
        tokens = [tk.strip(".,;:!?¿¡\"'()") for tk in q_lower.split()]
        q_clean = " ".join(tokens)
        for w in word_set:
            if " " in w:
                if w in q_clean:
                    return True
            else:
                if w in tokens:
                    return True
        return False

    def _on_organize_proposal(self, routine_id: str, files_json: str, confirm_msg: str):
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

        # Keep the real file list so we can validate LLM output later
        self._organize_real_files = files

        # Show scanning message
        if confirm_msg:
            self._say(confirm_msg, force=True)
        else:
            self._say(get_line("organize_scanning", self.pet.name), force=True)

        if self._llm_enabled:
            # Ask LLM to categorize
            file_list_str = _json.dumps(files, ensure_ascii=False)
            prompt = t("llm_prompts.organize_categorize", file_list=file_list_str)
            context = self._build_llm_context(prompt)

            def _on_result(text):
                if text:
                    self._organize_ready.emit(text)
                else:
                    self._organize_ready.emit("")

            self._llm.generate(context, _on_result)
        else:
            from utils.desktop_organizer import categorize_by_extension
            plan = categorize_by_extension(files)
            self._present_organize_plan(plan)

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

        # Validate LLM plan: every filename must exist in the real scan
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
            # Accept only if the LLM matched at least half the real files
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

    def _present_organize_plan(self, plan: dict):
        """Show the organize plan to the user and wait for confirmation."""
        from utils.desktop_organizer import format_plan_summary
        # Filter out empty categories
        plan = {k: v for k, v in plan.items() if v}
        if not plan:
            self._say(get_line("organize_empty", self.pet.name), force=True)
            return

        summary = format_plan_summary(plan)
        proposal_line = get_line("organize_proposal", self.pet.name, summary=summary)
        if not proposal_line:
            proposal_line = f"🗂️ {summary} — ¿Lo hago?"
        self._say(proposal_line, force=True, timeout_ms=15000)
        # Set AFTER _say so the guard in _say doesn't block our own proposal,
        # but all subsequent external _say calls will be suppressed.
        self._pending_organize = plan
        # Show clickable Yes/No buttons (reliable fallback for short-word STT)
        self._confirm_buttons.show_at(
            self.x() + self._sprite_size // 2,
            self.y(),
            pet_height=self._sprite_size,
        )

    def _on_confirm_button(self, accepted: bool):
        """Handle click on the GUI Yes/No buttons."""
        self._confirm_buttons.hide()
        if self._pending_organize is None:
            return
        self._handle_organize_confirmation("sí" if accepted else "no")

    def _handle_organize_confirmation(self, question: str):
        """Check if user said yes or no to the pending organize plan."""
        import threading
        q_lower = question.strip().lower()
        plan = self._pending_organize

        affirm, deny = get_confirm_words()
        affirm = affirm or self._AFFIRM_FALLBACK
        deny = deny or self._DENY_FALLBACK

        if self._match_words(q_lower, affirm):
            self._confirm_buttons.hide()
            self._pending_organize = None
            self._say(get_line("organize_executing", self.pet.name), force=True)

            def _do_move():
                from utils.desktop_organizer import execute_organize_plan
                result = execute_organize_plan(plan)
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

            t = threading.Thread(target=_do_move, name="organize-exec", daemon=True)
            t.start()

        elif self._match_words(q_lower, deny):
            self._confirm_buttons.hide()
            self._pending_organize = None
            self._say(get_line("organize_cancelled", self.pet.name), force=True)
        else:
            # Unrecognized — ask again (clear before _say, re-set after)
            self._pending_organize = None
            self._say(get_line("organize_confirm_retry", self.pet.name), force=True)
            self._pending_organize = plan

    # --- State changes ---

    def _on_state_change(self, old: PetState, new: PetState):
        """React to pet state transitions."""
        pass  # Animation handled by _on_anim_tick

    def _end_temp_state(self):
        """Return to IDLE after a temporary state (happy, eating, attacking, peeking)."""
        if self.pet.state in (PetState.HAPPY, PetState.EATING, PetState.ATTACKING,
                              PetState.PEEKING, PetState.JUMPING, PetState.HURT,
                              PetState.TALKING, PetState.DYING,
                              PetState.DANCE, PetState.GETTING_PET):
            log.debug("END_TEMP %s -> IDLE pos=(%d,%d)", self.pet.state.name, self.x(), self.y())
            self.pet.set_state(PetState.IDLE)

    def _start_fall_safety(self):
        """Start a safety timer to force-land the pet if FALLING persists too long."""
        if not self._fall_safety_timer.isActive():
            self._fall_safety_timer.start(3000)

    def _cancel_fall_safety(self):
        """Cancel the fall safety timer (pet landed normally)."""
        self._fall_safety_timer.stop()

    def _force_land(self):
        """Safety net: if the pet is still FALLING after the timeout, snap to ground."""
        if self.pet.state != PetState.FALLING:
            return
        self._refresh_screen_bounds()
        ground_y = self.movement._ground_y
        log.warning("FORCE_LAND stuck falling pos=(%d,%d) -> ground_y=%d",
                    self.x(), self.y(), ground_y)
        self.movement.set_position(self.movement.x, ground_y)
        self.move(self.movement.x, self.movement.y)
        self.pet.set_state(PetState.IDLE)

    # --- Gamer mode ---

    def toggle_gamer_mode(self, enabled: bool):
        """Toggle gamer mode: suppress all distractions while gaming.

        On activation, saves current values of always_on_top, window_push_enabled,
        silent_mode, and gravity in memory, then disables everything (silent on).
        On deactivation, restores the saved values.
        """
        if enabled and not self._gamer_mode:
            # Save current values
            self._gamer_saved = {
                "always_on_top": self._config.get("always_on_top", True),
                "window_push_enabled": self._config.get("window_push_enabled", True),
                "silent_mode": self._config.get("silent_mode", False),
                "gravity": self._config.get("gravity", False),
            }
            # Apply gamer settings
            self._config["always_on_top"] = False
            self._config["window_push_enabled"] = False
            self._config["silent_mode"] = True
            self._config["gravity"] = False
            self._gamer_mode = True
            self._routine_manager.pause_all()
            self.reload_config()
            log.info("GAMER_MODE enabled — saved %s", self._gamer_saved)

        elif not enabled and self._gamer_mode:
            # Restore saved values
            if self._gamer_saved:
                for key, val in self._gamer_saved.items():
                    self._config[key] = val
                self._gamer_saved = None
            self._gamer_mode = False
            self._last_user_interaction = time.monotonic()  # reset boredom clock
            self._routine_manager.resume_all()
            self.reload_config()
            log.info("GAMER_MODE disabled — settings restored")

    # --- Config reload ---

    def reload_config(self):
        """Apply in-memory config after settings change (does not re-read from disk)."""
        self.pet.name = self._config.get("pet_name", "Jacky")
        self.movement._speed = self._config.get("movement_speed", 3)
        self.movement.set_gravity(self._config.get("gravity", False))
        self._llm_enabled = self._config.get("llm_enabled", False)
        self._silent_mode = self._config.get("silent_mode", False)
        # Reload language if changed
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
            self.show()  # re-show after setWindowFlags hides the widget
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

        # Re-register global hotkey if shortcut changed
        new_shortcut = self._config.get("listen_shortcut", "ctrl+shift+space")
        self._global_hotkey.update_shortcut(new_shortcut)

        # Re-apply scheduler intervals (register handles cleanup of old timers)
        self._setup_scheduler()

        # Reload routines (picks up new/changed/removed routine files)
        self._routine_manager.load()

        # Toggle logging level at runtime
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

    # --- Greeting ---

    _NAME_GAME_KEYS = ("clippy", "cortana", "alexa", "siri", "navi", "chatgpt")

    def start(self):
        """Show the pet and say hello."""
        self.show()
        self._remove_dwm_border()
        self._system_events.start()
        if self._config.get("peer_interaction_enabled", True):
            max_peers = self._config.get("max_peer_instances", 5)
            self._peer_discovery.start(poll_interval_ms=500, max_peers=max_peers)
        name_lower = self.pet.name.lower()
        egg = get_line(f"name_game_{name_lower}", self.pet.name) if name_lower in self._NAME_GAME_KEYS else None
        greeting = egg if egg else get_line("greeting", self.pet.name)
        QTimer.singleShot(500, lambda: self._say(greeting))

    def _remove_dwm_border(self):
        """Remove the DWM shadow/border and apply platform-specific topmost level.

        On macOS this also schedules set_topmost() for the next event-loop tick
        so the NSWindow is guaranteed to exist before we try to set its level.
        """
        wid = int(self.winId())
        remove_dwm_border(wid)
        if sys.platform == "darwin":
            QTimer.singleShot(0, lambda: set_topmost(int(self.winId())))

