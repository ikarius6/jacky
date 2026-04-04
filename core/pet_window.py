import os
import logging
import random
import datetime

from PyQt6.QtWidgets import QWidget, QSystemTrayIcon, QMenu
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QIcon, QPixmap, QAction

from core.pet import Pet, PetState
from core.animation import AnimationController
from core.movement import MovementEngine
from core.character import get_character, get_sprites_dir
from core.scheduler import Scheduler
from core.window_interactions import WindowInteractionHandler
from interaction.click_handler import ClickHandler
from interaction.context_menu import PetContextMenu, DEFAULT_PERMISSIONS, PERMISSION_DEFS
from interaction.window_awareness import WindowAwareness
from speech.bubble import SpeechBubble
from speech.dialogue import get_line
from speech.llm_provider import create_llm_provider
from utils.config_manager import load_config
from utils.dwm_helpers import remove_dwm_border

log = logging.getLogger("pet_window")


class PetWindow(QWidget):
    """Main transparent frameless window that IS the pet."""

    _llm_text_ready = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._config = load_config()
        self._sprite_size = self._config.get("sprite_size", 128)

        # Window setup — fully transparent, no border, no shadow
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet("background:transparent;")
        self.setFixedSize(self._sprite_size, self._sprite_size)

        # Core components
        self.pet = Pet(name=self._config.get("pet_name", "Jacky"))
        self._character_name = self._config.get("character", "placeholder")
        self._char_cfg = get_character(self._character_name)
        sprites_dir = get_sprites_dir(self._character_name)
        self.animation = AnimationController(
            sprites_dir,
            sprite_size=self._sprite_size,
            fps=self._char_cfg.get("fps", 6),
            layout=self._char_cfg.get("type", "flat"),
            state_map=self._char_cfg.get("state_map"),
            flip_states=self._char_cfg.get("flip_states"),
        )
        self.movement = MovementEngine(
            sprite_size=self._sprite_size,
            speed=self._config.get("movement_speed", 3),
        )
        self._apply_dpi_scale()
        self.scheduler = Scheduler()

        # LLM (must be initialized before context menu)
        self._llm = create_llm_provider(self._config)
        self._llm_enabled = self._config.get("llm_enabled", False)
        self._llm_pending = False
        self._llm_text_ready.connect(self._say)

        # Interaction components
        self._click_handler = ClickHandler(self)
        self._context_menu = PetContextMenu(self)
        self._window_awareness = WindowAwareness(self)
        self._window_interactions = WindowInteractionHandler(self)
        self._bubble = SpeechBubble()

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

        # Animation timer
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._anim_timer.start(self.animation.frame_interval_ms)

        # Movement timer (~30 FPS)
        self._move_timer = QTimer(self)
        self._move_timer.timeout.connect(self._on_move_tick)
        self._move_timer.start(33)

        # Pet state change listener
        self.pet.on_state_change(self._on_state_change)

        # Setup scheduler events
        self._setup_scheduler()

        # Setup window awareness
        self._setup_window_awareness()

        # System tray
        self._setup_tray()

        # Initial position: bottom center of screen
        self._init_position()

    def _perm(self, key: str) -> bool:
        """Check a granular permission from config['permissions']."""
        perms = self._config.get("permissions", DEFAULT_PERMISSIONS)
        return perms.get(key, True)

    def _resolve_sprites_dir(self) -> str:
        """Legacy fallback — prefer get_sprites_dir(character_name)."""
        from utils.paths import get_data_dir
        sprite_set = self._config.get("sprite_set", "placeholder")
        return os.path.join(get_data_dir(), "sprites", sprite_set)

    def _apply_dpi_scale(self):
        """Pass the screen DPI scale to the movement engine for win32 coord conversion."""
        screen = self._current_screen()
        if screen:
            self.movement.set_dpi_scale(screen.devicePixelRatio())

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
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QPoint
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
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QRect
        screens = QApplication.screens()
        if not screens:
            return QRect(0, 0, 1920, 1080)
        result = screens[0].availableGeometry()
        for s in screens[1:]:
            result = result.united(s.availableGeometry())
        return result

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
        from PyQt6.QtWidgets import QApplication
        rects = []
        for s in QApplication.screens():
            g = s.availableGeometry()
            rects.append((g.x(), g.y(), g.x() + g.width(), g.y() + g.height()))
        self.movement.update_screen_rects(rects)

    def _setup_scheduler(self):
        idle_range = tuple(self._config.get("idle_interval", [5, 15]))
        chat_range = tuple(self._config.get("chat_interval", [20, 60]))
        win_range = tuple(self._config.get("window_check_interval", [10, 30]))

        self.scheduler.register("walk", self._scheduled_walk, idle_range)
        self.scheduler.register("chat", self._scheduled_chat, chat_range)
        if self._config.get("window_interaction_enabled", True):
            self.scheduler.register("window_interact", self._window_interactions.scheduled_interact, win_range)

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
        # Use a small pixmap as icon
        icon_pm = QPixmap(32, 32)
        icon_pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(icon_pm)
        p.setBrush(Qt.GlobalColor.cyan)
        p.drawEllipse(4, 4, 24, 24)
        p.end()
        self._tray.setIcon(QIcon(icon_pm))
        self._tray.setToolTip(f"{self.pet.name} - Desktop Pet")

        tray_menu = QMenu()
        show_action = QAction(f"Show {self.pet.name}", tray_menu)
        show_action.triggered.connect(self._bring_to_front)
        tray_menu.addAction(show_action)

        settings_action = QAction("Settings", tray_menu)
        settings_action.triggered.connect(lambda: self._context_menu._open_settings())
        tray_menu.addAction(settings_action)

        tray_menu.addSeparator()
        quit_action = QAction("Quit", tray_menu)
        quit_action.triggered.connect(self.on_quit)
        tray_menu.addAction(quit_action)

        self._tray.setContextMenu(tray_menu)
        self._tray.show()

    def _bring_to_front(self):
        self.show()
        self.raise_()

    # --- Paint ---

    def paintEvent(self, event):
        frame = self.animation.current_frame()
        if frame is None:
            log.warning("PAINT frame=None anim_state='%s' pos=(%d,%d) visible=%s",
                        self.animation.current_state, self.x(), self.y(), self.isVisible())
            return
        painter = QPainter(self)
        painter.drawPixmap(0, 0, frame)
        painter.end()

    # --- Mouse events ---

    def mousePressEvent(self, event):
        self._click_handler.handle_press(event)

    def mouseMoveEvent(self, event):
        self._click_handler.handle_move(event)

    def mouseReleaseEvent(self, event):
        self._click_handler.handle_release(event)

    # --- Click handler callbacks ---

    def on_pet_clicked(self):
        """Left-click: pet reaction."""
        log.info("ACTION on_pet_clicked pos=(%d,%d)", self.x(), self.y())
        self.pet.set_state(PetState.HAPPY)
        self._say(get_line("petted", self.pet.name))
        self._temp_state_timer.start(2000)

    def on_feed(self):
        """Feed from context menu."""
        log.info("ACTION on_feed pos=(%d,%d)", self.x(), self.y())
        self.pet.set_state(PetState.EATING)
        self._say(get_line("fed", self.pet.name))
        self._temp_state_timer.start(3000)

    def on_attack(self):
        """Attack from context menu: shooting if available, else slashing."""
        log.info("ACTION on_attack pos=(%d,%d)", self.x(), self.y())
        if "shooting" in self.animation.available_states:
            self.pet.set_state(PetState.SHOOTING)
        elif "slashing" in self.animation.available_states:
            self.pet.set_state(PetState.SLASHING)
        else:
            self.pet.set_state(PetState.INTERACTING)
        self._temp_state_timer.start(2000)

    def on_ask(self, question: str):
        """User asked a direct question via the Preguntar dialog."""
        if not self._llm_enabled:
            return
        if self._llm_pending:
            self._say("¡Espera, aún estoy pensando! >_<")
            return
        self._llm_pending = True
        context = self._build_llm_context(f"The user asks you directly: \"{question}\"")
        self._say("Hmm, déjame pensar...", timeout_ms=60000)
        self._llm.generate(context, self._on_ask_response)

    def on_drag_start(self):
        """User started dragging."""
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
        self.pet.set_state(PetState.IDLE)
        self.scheduler.resume_all()  # resume paused timers, don't re-register

    def show_context_menu(self, pos: QPoint):
        self._context_menu.show_at(pos)

    def on_quit(self):
        """Graceful exit."""
        self._say(get_line("farewell", self.pet.name))
        QTimer.singleShot(2000, self._do_quit)

    def _do_quit(self):
        self.scheduler.stop_all()
        self._window_awareness.stop()
        self._bubble.hide()
        self._tray.hide()
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().quit()

    # --- Animation tick ---

    def _on_anim_tick(self):
        anim_name = self.pet.get_animation_name()
        if anim_name not in self.animation.available_states:
            log.warning("ANIM_MISS state='%s' not in available=%s pos=(%d,%d)",
                        anim_name, self.animation.available_states, self.x(), self.y())
        self.animation.set_state(anim_name)
        self.animation.tick()
        self.update()

    # --- Movement tick ---

    def _on_move_tick(self):
        if self.pet.state != PetState.DRAGGED:
            # Keep screen bounds fresh (handles resolution/scaling changes)
            self._refresh_screen_bounds()

            if self.pet.state in (PetState.WALKING, PetState.RUNNING):
                self.movement.speed_multiplier = 2.0 if self.pet.state == PetState.RUNNING else 1.0
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
                    self.pet.set_state(PetState.IDLE)
            else:
                pass  # No gravity — pet stays where it is

        # Always keep bubble following the pet
        self._update_bubble_pos()

    # --- Scheduled events ---

    def _scheduled_walk(self):
        if self.pet.state not in (PetState.IDLE,):
            return
        log.info("SCHED walk from pos=(%d,%d)", self.x(), self.y())
        self.movement.pick_random_target()
        # 30% chance to run instead of walk (if character supports it)
        if random.random() < 0.3 and "run_right" in self.animation.available_states:
            self.pet.set_state(PetState.RUNNING)
        else:
            self.pet.set_state(PetState.WALKING)

    def _scheduled_chat(self):
        log.info("SCHED chat state=%s pos=(%d,%d)", self.pet.state.name, self.x(), self.y())
        if self.pet.state in (PetState.DRAGGED, PetState.TALKING):
            return

        # Check time for late-night comments
        hour = datetime.datetime.now().hour
        if hour >= 23 or hour < 5:
            self._say(get_line("late_night", self.pet.name))
            return

        if self._llm_enabled:
            if self._llm_pending:
                log.debug("SCHED chat skipped — LLM request already pending")
                return
            self._llm_pending = True
            context = self._build_llm_context("idle chatter")
            self._llm.generate(context, self._on_llm_response)
        else:
            self._say(get_line("idle", self.pet.name))

    # --- Speech ---

    def _say(self, text: str | None, timeout_ms: int = 0):
        """Show a speech bubble with text.

        timeout_ms: override auto-calculated timeout (0 = auto).
        """
        if not text:
            return
        log.info("SAY state=%s pos=(%d,%d) text='%s'", self.pet.state.name, self.x(), self.y(), text[:80])
        old_state = self.pet.state
        _KEEP_ANIM = (PetState.HAPPY, PetState.EATING, PetState.DRAGGED,
                     PetState.SHOOTING, PetState.SLASHING, PetState.THROWING,
                     PetState.SLIDING, PetState.INTERACTING)
        if old_state not in _KEEP_ANIM:
            self.pet.set_state(PetState.TALKING)

        anchor_x = self.x() + self._sprite_size // 2
        anchor_y = self.y()
        if timeout_ms <= 0:
            min_timeout = self._config.get("bubble_timeout", 5) * 1000
            word_count = len(text.split())
            timeout_ms = max(min_timeout, int(word_count * 400))
        self._bubble.show_message(text, anchor_x, anchor_y, timeout_ms=timeout_ms)

        # Return to IDLE after bubble hides — never restore transient states
        # that could leave the pet stuck (PEEKING, FALLING, INTERACTING, etc.)
        # Uses _talk_end_timer so a new _say() cancels any pending timer.
        if old_state not in _KEEP_ANIM:
            self._talk_end_timer.start(timeout_ms)

    def _end_talk_to_idle(self):
        if self.pet.state == PetState.TALKING:
            log.debug("END_TALK -> IDLE pos=(%d,%d)", self.x(), self.y())
            self.pet.set_state(PetState.IDLE)

    def _update_bubble_pos(self):
        if self._bubble.isVisible():
            self._bubble.update_position(
                self.x() + self._sprite_size // 2,
                self.y()
            )

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
        if hour >= 23 or hour < 6:
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
            self._llm_text_ready.emit(text)
        else:
            self._llm_text_ready.emit("No pude pensar en nada... ¡intenta de nuevo! >_<")

    # --- State changes ---

    def _on_state_change(self, old: PetState, new: PetState):
        """React to pet state transitions."""
        pass  # Animation handled by _on_anim_tick

    def _end_temp_state(self):
        """Return to IDLE after a temporary state (happy, eating, interacting, peeking)."""
        if self.pet.state in (PetState.HAPPY, PetState.EATING, PetState.INTERACTING,
                              PetState.PEEKING, PetState.SHOOTING, PetState.THROWING,
                              PetState.JUMPING, PetState.SLIDING, PetState.HURT,
                              PetState.TALKING, PetState.SLASHING):
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

    # --- Config reload ---

    def reload_config(self):
        """Reload config after settings change."""
        self._config = load_config()
        self.movement._speed = self._config.get("movement_speed", 3)
        self._llm_enabled = self._config.get("llm_enabled", False)
        self._llm = create_llm_provider(self._config)
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

        # Toggle logging level at runtime
        debug_on = self._config.get("debug_logging", False)
        root = logging.getLogger()
        root.setLevel(logging.DEBUG if debug_on else logging.WARNING)
        for h in root.handlers:
            h.setLevel(logging.DEBUG if debug_on else logging.WARNING)
        log.info("Logging level set to %s", "DEBUG" if debug_on else "WARNING")

        # Hot-swap character if changed
        new_char = self._config.get("character", "placeholder")
        if new_char != self._character_name:
            self._character_name = new_char
            self._char_cfg = get_character(new_char)
            sprites_dir = get_sprites_dir(new_char)
            self.animation = AnimationController(
                sprites_dir,
                sprite_size=self._sprite_size,
                fps=self._char_cfg.get("fps", 6),
                layout=self._char_cfg.get("type", "flat"),
                state_map=self._char_cfg.get("state_map"),
                flip_states=self._char_cfg.get("flip_states"),
            )
            self._anim_timer.setInterval(self.animation.frame_interval_ms)

    # --- Greeting ---

    def start(self):
        """Show the pet and say hello."""
        self.show()
        self._remove_dwm_border()
        QTimer.singleShot(500, lambda: self._say(get_line("greeting", self.pet.name)))

    def _remove_dwm_border(self):
        """Use Windows DWM API to remove the shadow/border around the window."""
        remove_dwm_border(int(self.winId()))
