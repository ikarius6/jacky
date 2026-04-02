import os
import logging
import random
import datetime
import ctypes
import ctypes.wintypes

from PyQt6.QtWidgets import QWidget, QSystemTrayIcon, QMenu
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QIcon, QPixmap, QAction, QCursor

from core.pet import Pet, PetState
from core.animation import AnimationController
from core.movement import MovementEngine
from core.character import get_character, get_sprites_dir
from core.scheduler import Scheduler
from interaction.click_handler import ClickHandler
from interaction.context_menu import PetContextMenu
from interaction.window_awareness import WindowAwareness, _is_junk_window
from speech.bubble import SpeechBubble
from speech.dialogue import get_line, get_app_comment
from speech.llm_provider import OllamaProvider
from utils.config_manager import load_config, save_config
from utils.win32_helpers import WindowInfo, get_foreground_window

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
        self._llm = OllamaProvider(
            base_url=self._config.get("ollama_url", "http://localhost:11434"),
            model=self._config.get("ollama_model", "llama3"),
        )
        self._llm_enabled = self._config.get("llm_enabled", False)
        self._llm_text_ready.connect(self._say)

        # Interaction components
        self._click_handler = ClickHandler(self)
        self._context_menu = PetContextMenu(self)
        self._window_awareness = WindowAwareness(self)
        self._bubble = SpeechBubble()

        # State tracking
        self._temp_state_timer = QTimer(self)
        self._temp_state_timer.setSingleShot(True)
        self._temp_state_timer.timeout.connect(self._end_temp_state)

        # Window drag tracking
        self._dragging_window_hwnd = None

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

    def _resolve_sprites_dir(self) -> str:
        """Legacy fallback — prefer get_sprites_dir(character_name)."""
        sprite_set = self._config.get("sprite_set", "placeholder")
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "sprites", sprite_set)

    def _apply_dpi_scale(self):
        """Pass the screen DPI scale to the movement engine for win32 coord conversion."""
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
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

    def _screen_geo(self):
        """Return the available screen geometry from Qt (logical pixels)."""
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            return screen.availableGeometry()
        # Fallback
        from PyQt6.QtCore import QRect
        return QRect(0, 0, 1920, 1080)

    def _refresh_screen_bounds(self):
        """Push Qt screen bounds into the movement engine."""
        geo = self._screen_geo()
        self.movement.update_bounds(
            geo.x(), geo.y(),
            geo.x() + geo.width(),
            geo.y() + geo.height(),
        )

    def _setup_scheduler(self):
        idle_range = tuple(self._config.get("idle_interval", [5, 15]))
        chat_range = tuple(self._config.get("chat_interval", [20, 60]))
        win_range = tuple(self._config.get("window_check_interval", [10, 30]))

        self.scheduler.register("walk", self._scheduled_walk, idle_range)
        self.scheduler.register("chat", self._scheduled_chat, chat_range)
        if self._config.get("window_interaction_enabled", True):
            self.scheduler.register("window_interact", self._scheduled_window_interact, win_range)

    def _setup_window_awareness(self):
        if not self._config.get("window_interaction_enabled", True):
            return
        self._window_awareness.set_push_enabled(self._config.get("window_push_enabled", True))
        self._window_awareness.set_callbacks(
            on_opened=self._on_window_opened,
            on_closed=self._on_window_closed,
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
        context = self._build_llm_context(f"The user asks you directly: \"{question}\"")
        self._say("Hmm, déjame pensar...")
        self._llm.generate(context, self._on_llm_response)

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
        self.movement.set_position_after_drop(pos.x(), pos.y())
        if self.movement.is_airborne:
            self.pet.set_state(PetState.FALLING)
        else:
            self.pet.set_state(PetState.IDLE)
        self._setup_scheduler()  # re-register timers

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
                if self._dragging_window_hwnd is not None:
                    self._window_awareness.drag_window_tick(
                        self._dragging_window_hwnd,
                        self.movement.x, self.movement.y,
                        self._sprite_size,
                    )

                if not still_moving:
                    self.movement.speed_multiplier = 1.0
                    self._dragging_window_hwnd = None
                    log.debug("WALK_DONE pos=(%d,%d)", self.x(), self.y())
                    self.pet.set_state(PetState.IDLE)
            else:
                self.movement.apply_gravity()
                self.move(self.movement.x, self.movement.y)
                # Switch to falling animation if airborne but not already falling
                if self.movement.is_airborne and self.pet.state == PetState.IDLE:
                    log.info("GRAVITY airborne detected pos=(%d,%d)", self.x(), self.y())
                    self.pet.set_state(PetState.FALLING)
                # Land after falling
                if self.pet.state == PetState.FALLING and not self.movement.is_airborne:
                    log.info("GRAVITY landed pos=(%d,%d)", self.x(), self.y())
                    self.pet.set_state(PetState.IDLE)

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
            context = self._build_llm_context("idle chatter")
            self._llm.generate(context, self._on_llm_response)
        else:
            self._say(get_line("idle", self.pet.name))

    def _scheduled_window_interact(self):
        if self.pet.state in (PetState.DRAGGED, PetState.FALLING, PetState.PEEKING):
            return

        action = random.choices(
            ["comment", "push", "peek", "shake", "minimize",
             "sit", "resize", "knock", "drag", "tidy", "topple"],
            weights=[0.25, 0.10, 0.10, 0.10, 0.05,
                     0.10, 0.08, 0.07, 0.05, 0.05, 0.05],
            k=1
        )[0]
        log.info("SCHED window_interact action=%s state=%s pos=(%d,%d)", action, self.pet.state.name, self.x(), self.y())

        if action == "comment":
            self._comment_on_window()
        elif action == "push":
            self._try_push()
        elif action == "peek":
            self._try_peek()
        elif action == "shake":
            self._try_shake()
        elif action == "minimize":
            self._try_minimize()
        elif action == "sit":
            self._try_sit_on_window()
        elif action == "resize":
            self._try_resize()
        elif action == "knock":
            self._try_knock()
        elif action == "drag":
            self._try_drag()
        elif action == "tidy":
            self._try_tidy()
        elif action == "topple":
            self._try_topple()

    # --- Window awareness callbacks ---

    def _on_window_opened(self, win: WindowInfo):
        if self.pet.state == PetState.DRAGGED:
            return
        if self._llm_enabled:
            ctx = f"A new window just opened: '{win.title}'. React to it briefly."
            self._llm.generate(ctx, self._on_llm_response)
        else:
            comment = get_app_comment(win.title, self.pet.name, process_name=win.process_name)
            if comment:
                self._say(comment)

    def _on_window_closed(self, win: WindowInfo):
        if self.pet.state == PetState.DRAGGED:
            return
        if random.random() < 0.3:  # Don't always comment on closes
            if self._llm_enabled:
                ctx = f"The window '{win.title}' just closed. React briefly."
                self._llm.generate(ctx, self._on_llm_response)
            else:
                self._say(get_line("window_closed", self.pet.name, app=win.title))

    # --- Window interaction behaviors ---

    def _comment_on_window(self):
        windows = self._window_awareness.get_interesting_windows()
        if not windows:
            return

        # 50% chance to comment on the foreground window if it's interesting
        fg = get_foreground_window()
        #print(f"Foreground window: {fg.title, fg.process_name}")
        if fg and random.random() < 0.5:
            if not _is_junk_window(fg.title, fg.process_name):
                target = fg
            else:
                target = random.choice(windows)
        else:
            target = random.choice(windows)

        if self._llm_enabled:
            ctx = f"I just noticed a window: '{target.title}' ({target.process_name}). Comment on it."
            self._llm.generate(ctx, self._on_llm_response)
        else:
            comment = get_app_comment(
                target.title, self.pet.name, process_name=target.process_name
            )
            if comment:
                self._say(comment)

    def _try_push(self):
        if not self._config.get("window_push_enabled", True):
            return
        pushed = self._window_awareness.try_push_window(
            self.movement.x, self.movement.y
        )
        if pushed:
            log.info("WIN_ACT push pos=(%d,%d)", self.x(), self.y())
            self.pet.set_state(PetState.INTERACTING)
            self._say(get_line("window_push", self.pet.name))
            self._temp_state_timer.start(2000)

    def _try_peek(self):
        if self.pet.state not in (PetState.IDLE, PetState.INTERACTING):
            return
        result = self._window_awareness.get_peek_position(self._sprite_size)
        if not result:
            return
        # Save position so we can return after the peek
        self._pre_peek_pos = (self.movement.x, self.movement.y)
        log.info("WIN_ACT peek from=(%d,%d) to=(%d,%d)", self.x(), self.y(), result["x"], result["y"])
        self.pet.set_state(PetState.PEEKING)
        self.movement.set_position(result["x"], result["y"])
        self.move(self.movement.x, self.movement.y)
        self._say(get_line("peeking", self.pet.name))
        QTimer.singleShot(3000, self._return_from_peek)

    def _return_from_peek(self):
        """Restore pet to its pre-peek position so it doesn't get stranded."""
        if not getattr(self, '_pre_peek_pos', None):
            return
        x, y = self._pre_peek_pos
        self._pre_peek_pos = None
        log.info("PEEK_RETURN to=(%d,%d) from pos=(%d,%d)", x, y, self.x(), self.y())
        self.movement.set_position(x, y)
        self.move(self.movement.x, self.movement.y)
        if self.pet.state not in (PetState.DRAGGED, PetState.WALKING, PetState.RUNNING):
            self.pet.set_state(PetState.IDLE)

    def _try_shake(self):
        if not self._config.get("window_push_enabled", True):
            return
        target = self._window_awareness.try_shake_window(
            self.movement.x, self.movement.y
        )
        if not target:
            return
        log.info("WIN_ACT shake target='%s' pos=(%d,%d)", target.title, self.x(), self.y())
        self.pet.set_state(PetState.INTERACTING)
        self._say(get_line("window_shake", self.pet.name))
        self._shake_hwnd = target.hwnd
        self._shake_step = 0
        self._shake_timer = QTimer(self)
        self._shake_timer.timeout.connect(self._on_shake_tick)
        self._shake_timer.start(50)

    def _on_shake_tick(self):
        if not self._window_awareness.do_shake_step(self._shake_hwnd, self._shake_step):
            self._shake_timer.stop()
            self._shake_timer.deleteLater()
            self._temp_state_timer.start(1000)
            return
        self._shake_step += 1

    def _try_minimize(self):
        if not self._config.get("window_push_enabled", True):
            return
        target = self._window_awareness.try_minimize_window(
            self.movement.x, self.movement.y
        )
        if target:
            log.info("WIN_ACT minimize target='%s' pos=(%d,%d)", target.title, self.x(), self.y())
            if "shooting" in self.animation.available_states:
                self.pet.set_state(PetState.SHOOTING)
            elif "slashing" in self.animation.available_states:
                self.pet.set_state(PetState.SLASHING)
            else:
                self.pet.set_state(PetState.INTERACTING)
            self._say(get_line("window_minimize", self.pet.name))
            self._temp_state_timer.start(2000)

    def _try_sit_on_window(self):
        if self.pet.state not in (PetState.IDLE, PetState.INTERACTING):
            return
        result = self._window_awareness.get_titlebar_position(self._sprite_size)
        if not result:
            return
        log.info("WIN_ACT sit from=(%d,%d) to=(%d,%d)", self.x(), self.y(), result["x"], result["y"])
        self.pet.set_state(PetState.IDLE)
        self.movement.set_position(result["x"], result["y"])
        self.move(self.movement.x, self.movement.y)
        self._say(get_line("window_sit", self.pet.name))
        self._temp_state_timer.start(5000)

    def _try_resize(self):
        if not self._config.get("window_push_enabled", True):
            return
        target = self._window_awareness.try_resize_window(
            self.movement.x, self.movement.y
        )
        if target:
            log.info("WIN_ACT resize target='%s' pos=(%d,%d)", target.title, self.x(), self.y())
            self.pet.set_state(PetState.INTERACTING)
            self._say(get_line("window_resize", self.pet.name))
            self._temp_state_timer.start(2000)

    def _try_knock(self):
        target = self._window_awareness.try_knock_window()
        if target:
            log.info("WIN_ACT knock target='%s' pos=(%d,%d)", target.title, self.x(), self.y())
            self.pet.set_state(PetState.INTERACTING)
            self._say(get_line("window_knock", self.pet.name))
            self._temp_state_timer.start(2000)

    def _try_drag(self):
        if self.pet.state not in (PetState.IDLE, PetState.INTERACTING):
            return
        if not self._config.get("window_push_enabled", True):
            return
        target = self._window_awareness.start_drag_window(
            self.movement.x, self.movement.y
        )
        if not target:
            return
        log.info("WIN_ACT drag target='%s' hwnd=%s pos=(%d,%d)", target.title, target.hwnd, self.x(), self.y())
        self._dragging_window_hwnd = target.hwnd
        self.pet.set_state(PetState.WALKING)
        self.movement.pick_random_target()
        self._say(get_line("window_drag", self.pet.name))
        # Drag ends when the walk finishes (handled in _on_move_tick)

    def _try_tidy(self):
        if not self._config.get("window_push_enabled", True):
            return
        success = self._window_awareness.try_tidy_windows()
        if success:
            log.info("WIN_ACT tidy pos=(%d,%d)", self.x(), self.y())
            self.pet.set_state(PetState.INTERACTING)
            self._say(get_line("window_tidy", self.pet.name))
            self._temp_state_timer.start(3000)

    def _try_topple(self):
        if not self._config.get("window_push_enabled", True):
            return
        toppled = self._window_awareness.try_topple_windows(
            self.movement.x, self.movement.y, self.pet.direction
        )
        if toppled:
            log.info("WIN_ACT topple pos=(%d,%d) dir=%d", self.x(), self.y(), self.pet.direction)
            if "shooting" in self.animation.available_states:
                self.pet.set_state(PetState.SHOOTING)
            else:
                self.pet.set_state(PetState.INTERACTING)
            self._say(get_line("window_topple", self.pet.name))
            self._temp_state_timer.start(2500)

    # --- Speech ---

    def _say(self, text: str | None):
        """Show a speech bubble with text."""
        if not text:
            return
        log.info("SAY state=%s pos=(%d,%d) text='%s'", self.pet.state.name, self.x(), self.y(), text[:80])
        old_state = self.pet.state
        if old_state not in (PetState.HAPPY, PetState.EATING, PetState.DRAGGED):
            self.pet.set_state(PetState.TALKING)

        anchor_x = self.x() + self._sprite_size // 2
        anchor_y = self.y()
        min_timeout = self._config.get("bubble_timeout", 5) * 1000
        word_count = len(text.split())
        timeout = max(min_timeout, int(word_count * 400))
        self._bubble.show_message(text, anchor_x, anchor_y, timeout_ms=timeout)

        # Return to IDLE after bubble hides — never restore transient states
        # that could leave the pet stuck (PEEKING, FALLING, INTERACTING, etc.)
        if old_state not in (PetState.HAPPY, PetState.EATING, PetState.DRAGGED):
            QTimer.singleShot(timeout, self._end_talk_to_idle)

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
        win_ctx = self._window_awareness.get_window_comment_context()
        parts.append(win_ctx)
        hour = datetime.datetime.now().hour
        parts.append(f"Current time: {datetime.datetime.now().strftime('%H:%M')}")
        return " | ".join(parts)

    def _on_llm_response(self, text: str | None):
        """Callback from LLM thread — emit signal for thread-safe delivery."""
        if text:
            self._llm_text_ready.emit(text)
        else:
            # Fallback to predefined
            fallback = get_line("idle", self.pet.name) or "..."
            self._llm_text_ready.emit(fallback)

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

    # --- Config reload ---

    def reload_config(self):
        """Reload config after settings change."""
        self._config = load_config()
        self.movement._speed = self._config.get("movement_speed", 3)
        self._llm_enabled = self._config.get("llm_enabled", False)
        self._llm._base_url = self._config.get("ollama_url", "http://localhost:11434").rstrip("/")
        self._llm._model = self._config.get("ollama_model", "llama3")
        self._window_awareness.set_enabled(self._config.get("window_interaction_enabled", True))
        self._window_awareness.set_push_enabled(self._config.get("window_push_enabled", True))
        self._context_menu.refresh_llm_state()

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
        try:
            hwnd = int(self.winId())
            dwmapi = ctypes.windll.dwmapi
            user32 = ctypes.windll.user32

            # DWMWA_NCRENDERING_POLICY = 2, DWMNCRP_DISABLED = 1
            policy = ctypes.c_int(1)
            dwmapi.DwmSetWindowAttribute(
                hwnd, 2, ctypes.byref(policy), ctypes.sizeof(policy)
            )

            # DWMWA_TRANSITIONS_FORCEDISABLED = 3
            disabled = ctypes.c_int(1)
            dwmapi.DwmSetWindowAttribute(
                hwnd, 3, ctypes.byref(disabled), ctypes.sizeof(disabled)
            )

            # Windows 11: set border colour to DWMWA_COLOR_NONE (0xFFFFFFFE)
            # DWMWA_BORDER_COLOR = 34
            color_none = ctypes.c_uint(0xFFFFFFFE)
            dwmapi.DwmSetWindowAttribute(
                hwnd, 34, ctypes.byref(color_none), ctypes.sizeof(color_none)
            )

            # Windows 11: disable rounded corners
            # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_DONOTROUND = 1
            corner = ctypes.c_int(1)
            dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner)
            )

            # Collapse the DWM frame to zero
            class MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", ctypes.c_int),
                    ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]
            margins = MARGINS(0, 0, 0, 0)
            dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))

            # Strip extended-style flags that can introduce borders
            GWL_EXSTYLE = -20
            WS_EX_DLGMODALFRAME = 0x0001
            WS_EX_CLIENTEDGE = 0x0200
            WS_EX_STATICEDGE = 0x00020000
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style &= ~(WS_EX_DLGMODALFRAME | WS_EX_CLIENTEDGE | WS_EX_STATICEDGE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

            # Force the frame change to take effect
            SWP_FRAMECHANGED = 0x0020
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER,
            )
        except Exception:
            pass
