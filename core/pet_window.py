import sys
import logging
import random
import datetime
import time

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPixmap, QImage, QTransform, QColor

from core.pet import Pet, PetState, ANIMATION_FALLBACKS
from core.animation import AnimationController
from core.movement import MovementEngine
from core.character import get_character, get_sprites_dir
from core.scheduler import Scheduler
from core.system_events import SystemEventsMonitor, SystemEvent
from core.window_interactions import WindowInteractionHandler
from core.peer_interactions import PeerInteractionHandler
from core.screen_interaction import ScreenInteractionHandler
from core.timer_manager import TimerManager
from core.routines.manager import RoutineManager
from interaction.click_handler import ClickHandler
from interaction.context_menu import PetContextMenu, DEFAULT_PERMISSIONS
from interaction.window_awareness import WindowAwareness
from interaction.peer_discovery import PeerDiscovery
from speech.bubble import SpeechBubble, ConfirmButtons
from speech.music_player_widget import MusicPlayerWidget
from speech.dialogue import get_line
from speech.llm_provider import create_llm_provider
from speech.voice import ElevenLabsTTSClient, AssemblyAISTTClient
from interaction.hotkey import GlobalHotkey
from utils.config_manager import load_config
from pal import remove_dwm_border, set_topmost
from utils.i18n import load_language, t

from core.mixins.window_mixin import WindowMixin
from core.mixins.tray_mixin import TrayMixin
from core.mixins.speech_mixin import SpeechMixin
from core.mixins.llm_mixin import LlmMixin
from core.mixins.boredom_mixin import BoredomMixin
from core.mixins.easter_egg_mixin import EasterEggMixin
from core.mixins.ask_mixin import AskMixin
from core.mixins.organize_mixin import OrganizeMixin
from core.mixins.routine_mixin import RoutineMixin
from core.mixins.timer_intent_mixin import TimerIntentMixin
from core.mixins.config_mixin import ConfigMixin
from core.mixins.collectible_mixin import CollectibleMixin
from core.mixins.music_mixin import MusicMixin

log = logging.getLogger("pet_window")


class PetWindow(
    ConfigMixin, WindowMixin, TrayMixin, SpeechMixin, LlmMixin,
    BoredomMixin, EasterEggMixin, AskMixin, OrganizeMixin,
    RoutineMixin, TimerIntentMixin, CollectibleMixin, MusicMixin,
    QWidget,
):
    """Main transparent frameless window that IS the pet."""

    _llm_text_ready = pyqtSignal(str)
    _llm_ask_ready = pyqtSignal(str)
    _intent_ready = pyqtSignal(object)   # IntentResult or None
    _organize_ready = pyqtSignal(str)    # LLM categorization JSON response
    _voice_transcript_ready = pyqtSignal(str)
    _voice_error_ready = pyqtSignal(str)
    _collectible_card_ready = pyqtSignal(str, str)  # (sprite_key, raw_json)
    _music_info_ready = pyqtSignal(object)  # MediaInfo or None

    def __init__(self):
        super().__init__()
        self._config = load_config()
        load_language(self._config.get("language", "es"))
        self._sprite_size = self._config.get("sprite_size", 128)
        self._always_on_top = self._config.get("always_on_top", True)

        # Window setup — fully transparent, no border, no shadow
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
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

        # LLM state
        self._llm = create_llm_provider(self._config)
        self._llm_enabled = self._config.get("llm_enabled", False)
        self._silent_mode = self._config.get("silent_mode", False)
        self._gamer_mode = False
        self._gamer_saved: dict | None = None
        self._music_mode = False
        self._llm_pending = False
        self._is_speaking = False
        self._pending_question = ""
        self._pending_organize: dict | None = None
        self._organize_real_files: list = []

        # Easter egg state
        self._appearance_mode: str | None = None
        self._barrel_roll_count = 0
        self._glitch_color_r = 255
        self._glitch_color_g = 0
        self._glitch_color_b = 200

        # Signal wiring
        self._llm_text_ready.connect(self._say)
        self._llm_ask_ready.connect(self._say_forced)
        self._organize_ready.connect(self._on_organize_llm_response)
        self._intent_ready.connect(self._on_intent_classified)
        self._collectible_card_ready.connect(self._on_collectible_card_llm)

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
        self._music_player = MusicPlayerWidget()
        self._music_player.prev_clicked.connect(self._music_prev)
        self._music_player.play_pause_clicked.connect(self._music_play_pause)
        self._music_player.next_clicked.connect(self._music_next)

        # Voice and hotkey
        self._tts_client = ElevenLabsTTSClient(
            api_key=self._config.get("elevenlabs_api_key", ""),
            voice_id=self._config.get("elevenlabs_voice_id", "U0W3edavfdI8ibPeeteQ"),
            model_id=self._config.get("elevenlabs_model", "eleven_flash_v2_5"),
            allow_cache_func=lambda: self._perm("allow_cache"),
        )
        self._tts_client.playback_finished.connect(self._on_tts_finished)
        self._stt_client = AssemblyAISTTClient(
            api_key=self._config.get("assemblyai_api_key", ""),
            model=self._config.get("assemblyai_model", "universal-streaming-multilingual"),
        )
        self._voice_transcript_ready.connect(self.on_ask)
        self._voice_error_ready.connect(
            lambda err: self._say(f"STT Error: {err}", force=True, skip_voice=True)
        )
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

        # State timers
        self._temp_state_timer = QTimer(self)
        self._temp_state_timer.setSingleShot(True)
        self._temp_state_timer.timeout.connect(self._end_temp_state)

        self._talk_end_timer = QTimer(self)
        self._talk_end_timer.setSingleShot(True)
        self._talk_end_timer.timeout.connect(self._end_talk_to_idle)

        self._fall_safety_timer = QTimer(self)
        self._fall_safety_timer.setSingleShot(True)
        self._fall_safety_timer.timeout.connect(self._force_land)

        # Easter egg timers
        self._barrel_roll_timer = QTimer(self)
        self._barrel_roll_timer.setInterval(150)
        self._barrel_roll_timer.timeout.connect(self._barrel_roll_tick)

        self._appearance_timer = QTimer(self)
        self._appearance_timer.setSingleShot(True)
        self._appearance_timer.timeout.connect(self._revert_appearance)

        self._glitch_tick_timer = QTimer(self)
        self._glitch_tick_timer.setInterval(80)
        self._glitch_tick_timer.timeout.connect(self._glitch_tick)

        # Boredom state
        self._BOREDOM_CALLOUT_MIN = 10
        self._BOREDOM_ERRATIC_MIN = 20
        self._BOREDOM_SELFTALK_MIN = 30
        self._BOREDOM_ASLEEP_MIN = 60
        self._BOREDOM_SELFTALK_INTERVAL_S = 120
        self._last_user_interaction: float = time.monotonic()
        self._boredom_level: int = 0
        self._boredom_asleep: bool = False
        self._last_selftalk: float = 0.0
        self._boredom_timer = QTimer(self)
        self._boredom_timer.setInterval(60_000)
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

        # Topmost reassertion timer
        self._topmost_timer = QTimer(self)
        self._topmost_timer.timeout.connect(self._reassert_topmost)
        if self._always_on_top:
            self._topmost_timer.start(5000)

        # Screen bounds throttle
        self._BOUNDS_REFRESH_INTERVAL_S = 2.0
        self._last_bounds_refresh = 0.0
        self._bounds_dirty = True
        self._connect_screen_signals()

        # Listeners
        self.pet.on_state_change(self._on_state_change)

        # Setup subsystems
        self._setup_scheduler()
        self._setup_window_awareness()
        self._setup_peer_discovery()
        self._system_events = SystemEventsMonitor(self)
        self._setup_system_events()
        self._setup_tray()
        self._init_collectibles()
        self._init_music()
        self._init_position()

    # --- Setup helpers ---

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
        self._system_events.event_triggered.connect(self._on_system_event)

    def _on_system_event(self, event: SystemEvent, data: dict):
        if event == SystemEvent.USER_RETURNED:
            self._touch_user_interaction()
        if self._silent_mode:
            return
        if self.pet.state == PetState.DRAGGED:
            return
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
        if self._llm_enabled and not self._llm_pending:
            pct = data.get("pct", "?")
            _LLM_PROMPTS = {
                SystemEvent.BATTERY_LOW:         t("llm_prompts.sys_battery_low", pct=pct),
                SystemEvent.BATTERY_CRITICAL:    t("llm_prompts.sys_battery_critical", pct=pct),
                SystemEvent.BATTERY_CHARGING:    t("llm_prompts.sys_battery_charging"),
                SystemEvent.BATTERY_DISCHARGING: t("llm_prompts.sys_battery_discharging"),
                SystemEvent.BATTERY_FULL:        t("llm_prompts.sys_battery_full"),
                SystemEvent.USER_RETURNED:       t("llm_prompts.sys_user_returned"),
            }
            prompt = _LLM_PROMPTS.get(event)
            if prompt:
                self._llm_pending = True
                ctx = self._build_llm_context(prompt)
                self._llm.generate(ctx, self._on_llm_response)
                return
        pct = data.get("pct", "")
        line = get_line(trigger, self.pet.name, pct=pct)
        if line:
            self._say(line)

    def _setup_peer_discovery(self):
        if not self._config.get("peer_interaction_enabled", True):
            return
        self._peer_discovery.on_peer_joined = self._peer_interactions.on_peer_joined
        self._peer_discovery.on_peer_left = self._peer_interactions.on_peer_left
        self._peer_discovery.on_event_received = self._peer_interactions.on_event_received

    # --- Paint ---

    def paintEvent(self, event):
        from PyQt6.QtGui import QImage, QPixmap, QTransform, QColor
        from PyQt6.QtCore import Qt
        frame = self.animation.current_frame()
        if frame is None:
            log.warning("PAINT frame=None anim_state='%s' pos=(%d,%d) visible=%s",
                        self.animation.current_state, self.x(), self.y(), self.isVisible())
            return
        if self._appearance_mode == "evil":
            img = frame.toImage().convertToFormat(QImage.Format.Format_ARGB32)
            img.invertPixels(QImage.InvertMode.InvertRgb)
            frame = QPixmap.fromImage(img)
        elif self._appearance_mode == "glitch":
            frame = frame.transformed(QTransform().scale(-1, 1))
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

    # --- User actions ---

    def on_pet_clicked(self):
        self._touch_user_interaction()
        if self._screen_interaction.is_active:
            self._screen_interaction.cancel()
            return
        if self._music_mode and self._current_song:
            title, artist = self._current_song
            text = t("ui.music_now_playing", title=title, artist=artist)
            self._say(text, force=True, timeout_ms=5000, skip_voice=True)
            return
        log.info("ACTION on_pet_clicked pos=(%d,%d)", self.x(), self.y())
        self.pet.set_state(PetState.GETTING_PET)
        self._say(get_line("petted", self.pet.name))
        self._temp_state_timer.start(2000)

    def on_feed(self):
        self._touch_user_interaction()
        if self._screen_interaction.is_active:
            self._screen_interaction.cancel()
        log.info("ACTION on_feed pos=(%d,%d)", self.x(), self.y())
        self.pet.set_state(PetState.EATING)
        self._say(get_line("fed", self.pet.name))
        self._temp_state_timer.start(3000)

    def on_attack(self):
        self._touch_user_interaction()
        if self._screen_interaction.is_active:
            self._screen_interaction.cancel()
        log.info("ACTION on_attack pos=(%d,%d)", self.x(), self.y())
        self.pet.set_state(PetState.ATTACKING)
        self._temp_state_timer.start(2000)

    def on_drag_start(self):
        if self._screen_interaction.is_active:
            self._screen_interaction.cancel()
        log.info("ACTION on_drag_start pos=(%d,%d)", self.x(), self.y())
        self.pet.set_state(PetState.DRAGGED)
        self.scheduler.pause_all()
        self.movement.stop()
        self._say(get_line("dragged", self.pet.name))

    def on_drag_end(self):
        pos = self.pos()
        log.info("ACTION on_drag_end pos=(%d,%d)", pos.x(), pos.y())
        self._refresh_screen_bounds()
        self._apply_dpi_scale()
        self.movement.set_position_after_drop(pos.x(), pos.y())
        if self.movement.gravity_enabled and self.movement.is_airborne:
            self.pet.set_state(PetState.FALLING)
        else:
            self.pet.set_state(PetState.IDLE)
        self.scheduler.resume_all()
        self._check_corner_exile(pos.x(), pos.y())

    def _check_corner_exile(self, x: int, y: int):
        margin = 20
        geo = self._screen_geo()
        left, top = geo.x(), geo.y()
        right = geo.x() + geo.width() - self._sprite_size
        bottom = geo.y() + geo.height() - self._sprite_size
        near_edge = (x - left <= margin or right - x <= margin
                     or y - top <= margin or bottom - y <= margin)
        if near_edge:
            line = get_line("corner_exile", self.pet.name)
            if line:
                self._say(line)

    def show_context_menu(self, pos):
        self._touch_user_interaction()
        self._context_menu.show_at(pos)

    def on_quit(self):
        self._say(get_line("farewell", self.pet.name))
        QTimer.singleShot(2000, self._do_quit)

    def _do_quit(self):
        if self._music_mode:
            self.toggle_music_mode(False)
        self.scheduler.stop_all()
        self._boredom_timer.stop()
        self._system_events.stop()
        self._peer_discovery.stop()
        self._window_awareness.stop()
        self._timer_manager.stop()
        self._routine_manager.stop()
        self._cleanup_collectibles()
        self._bubble.hide()
        self._music_player.hide()
        self._tray.hide()
        QApplication.instance().quit()

    # --- Animation tick ---

    def _on_anim_tick(self):
        anim_name = self.pet.get_animation_name()
        if anim_name not in self.animation.available_states:
            for alt in ANIMATION_FALLBACKS.get(anim_name, []):
                if alt in self.animation.available_states:
                    anim_name = alt
                    break
            else:
                log.warning("ANIM_MISS state='%s' not in available=%s pos=(%d,%d)",
                            anim_name, self.animation.available_states, self.x(), self.y())
        self.animation.set_facing(self.pet.direction < 0)
        self.animation.set_state(anim_name)
        self.animation.tick()
        self.update()

    # --- Movement tick ---

    def _on_move_tick(self):
        if self.pet.state != PetState.DRAGGED:
            self._maybe_refresh_screen_bounds()
            if self.pet.state in (PetState.WALKING, PetState.RUNNING):
                if self._screen_interaction.is_active:
                    self.movement.speed_multiplier = 4.0
                elif self.pet.state == PetState.RUNNING:
                    self.movement.speed_multiplier = 2.0
                else:
                    self.movement.speed_multiplier = 1.0
                still_moving = self.movement.tick()
                self.move(self.movement.x, self.movement.y)
                self.pet.direction = self.movement.direction
                if self._window_interactions.dragging_window_hwnd is not None:
                    self._window_awareness.drag_window_tick(
                        self._window_interactions.dragging_window_hwnd,
                        self.movement.x, self.movement.y, self._sprite_size,
                    )
                if not still_moving:
                    self.movement.speed_multiplier = 1.0
                    self._window_interactions.dragging_window_hwnd = None
                    log.debug("WALK_DONE pos=(%d,%d)", self.x(), self.y())
                    if self._screen_interaction.is_active:
                        self._screen_interaction.on_arrival()
                    else:
                        self.pet.set_state(PetState.IDLE)
                self._peer_interactions.check_peer_arrival()
            else:
                if self.movement.gravity_enabled:
                    self.movement.apply_gravity()
                    self.move(self.movement.x, self.movement.y)
                    _no_fall = (PetState.FALLING, PetState.DRAGGED, PetState.JUMPING)
                    if self.movement.is_airborne and self.pet.state not in _no_fall:
                        log.info("GRAVITY airborne detected state=%s pos=(%d,%d)",
                                 self.pet.state.name, self.x(), self.y())
                        self.pet.set_state(PetState.FALLING)
                        self._start_fall_safety()
                    elif self.pet.state == PetState.FALLING and not self.movement.is_airborne:
                        log.info("GRAVITY landed pos=(%d,%d)", self.x(), self.y())
                        self._cancel_fall_safety()
                        self.pet.set_state(PetState.IDLE)
        self._update_bubble_pos()

    # --- Scheduled events ---

    def _scheduled_walk(self):
        if self._boredom_asleep:
            return
        if self.pet.state not in (PetState.IDLE,):
            return
        log.info("SCHED walk from pos=(%d,%d)", self.x(), self.y())
        self.movement.pick_random_target()
        if random.random() < 0.3 and "run" in self.animation.available_states:
            self.pet.set_state(PetState.RUNNING)
        else:
            self.pet.set_state(PetState.WALKING)

    def _scheduled_chat(self):
        log.info("SCHED chat state=%s pos=(%d,%d)", self.pet.state.name, self.x(), self.y())
        if self._boredom_asleep or self._silent_mode or self._is_speaking:
            return
        if self.pet.state in (PetState.DRAGGED, PetState.TALKING):
            return
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
                return
            self._llm_pending = True
            context = self._build_llm_context(t("llm_prompts.idle_chat"))
            self._llm.generate(context, self._on_llm_response)
        else:
            if (hour >= 23 or hour < 5) and random.random() < 0.2:
                self._say(get_line("late_night", self.pet.name))
            else:
                self._say(get_line("idle", self.pet.name))

    # --- State management ---

    def _on_state_change(self, old: PetState, new: PetState):
        pass  # Animation handled by _on_anim_tick

    def _end_temp_state(self):
        if self.pet.state in (PetState.HAPPY, PetState.EATING, PetState.ATTACKING,
                              PetState.PEEKING, PetState.JUMPING, PetState.HURT,
                              PetState.TALKING, PetState.DYING,
                              PetState.DANCE, PetState.GETTING_PET):
            log.debug("END_TEMP %s -> IDLE pos=(%d,%d)", self.pet.state.name, self.x(), self.y())
            self.pet.set_state(PetState.IDLE)

    def _start_fall_safety(self):
        if not self._fall_safety_timer.isActive():
            self._fall_safety_timer.start(3000)

    def _cancel_fall_safety(self):
        self._fall_safety_timer.stop()

    def _force_land(self):
        if self.pet.state != PetState.FALLING:
            return
        self._refresh_screen_bounds()
        ground_y = self.movement._ground_y
        log.warning("FORCE_LAND stuck falling pos=(%d,%d) -> ground_y=%d",
                    self.x(), self.y(), ground_y)
        self.movement.set_position(self.movement.x, ground_y)
        self.move(self.movement.x, self.movement.y)
        self.pet.set_state(PetState.IDLE)

    # --- Startup ---

    _NAME_GAME_KEYS = ("clippy", "cortana", "alexa", "siri", "navi", "chatgpt")

    def start(self):
        self.show()
        self._remove_dwm_border()
        self._system_events.start()
        if self._config.get("peer_interaction_enabled", True):
            max_peers = self._config.get("max_peer_instances", 5)
            self._peer_discovery.start(poll_interval_ms=500, max_peers=max_peers)
        name_lower = self.pet.name.lower()
        egg = (get_line(f"name_game_{name_lower}", self.pet.name)
               if name_lower in self._NAME_GAME_KEYS else None)
        greeting = egg if egg else get_line("greeting", self.pet.name)
        QTimer.singleShot(500, lambda: self._say(greeting))

    def _remove_dwm_border(self):
        import sys
        wid = int(self.winId())
        remove_dwm_border(wid)
        if sys.platform == "darwin":
            QTimer.singleShot(0, lambda: set_topmost(int(self.winId())))
