import logging
import random

from PyQt6.QtCore import QTimer

from core.pet import PetState
from interaction.window_awareness import _is_junk_window
from speech.dialogue import get_line, get_app_comment
from pal import WindowInfo, get_foreground_window

log = logging.getLogger("window_interactions")

# Action → permission key mapping
_ACTION_PERM = {
    "comment":  "allow_comment",
    "push":     "allow_push",
    "peek":     "allow_peek",
    "shake":    "allow_shake",
    "minimize": "allow_minimize",
    "sit":      "allow_sit",
    "resize":   "allow_resize",
    "knock":    "allow_knock",
    "drag":     "allow_drag",
    "tidy":     "allow_tidy",
    "topple":   "allow_topple",
}

# Weighted probability for each action
_ACTION_WEIGHTS = {
    "comment": 0.25, "push": 0.10, "peek": 0.10, "shake": 0.10,
    "minimize": 0.05, "sit": 0.10, "resize": 0.08, "knock": 0.07,
    "drag": 0.05, "tidy": 0.05, "topple": 0.05,
}


class WindowInteractionHandler:
    """Encapsulates all window-interaction behaviours for the pet.

    Owns the scheduled interaction dispatcher, individual action methods,
    and the window open/close callbacks.  Keeps a back-reference to the
    parent ``PetWindow`` for access to shared state (pet, movement,
    animation, speech, etc.).
    """

    def __init__(self, pet_window):
        self._pw = pet_window

        # State owned by this handler
        self._pre_peek_pos = None
        self._shake_hwnd = None
        self._shake_step = 0
        self._shake_timer = None
        self.dragging_window_hwnd = None

    # ------------------------------------------------------------------
    # Scheduler entry point
    # ------------------------------------------------------------------

    def scheduled_interact(self):
        """Called by the Scheduler — pick a random permitted action."""
        pw = self._pw
        if pw._silent_mode:
            return
        if pw._is_speaking:
            log.debug("SCHED window_interact skipped — already speaking")
            return
        if pw.pet.state in (PetState.DRAGGED, PetState.FALLING, PetState.PEEKING):
            return

        actions = [a for a, perm in _ACTION_PERM.items() if pw._perm(perm)]
        if not actions:
            return
        weights = [_ACTION_WEIGHTS[a] for a in actions]

        action = random.choices(actions, weights=weights, k=1)[0]
        log.info("SCHED window_interact action=%s state=%s pos=(%d,%d)",
                 action, pw.pet.state.name, pw.x(), pw.y())

        handler = getattr(self, f"_do_{action}", None)
        if handler:
            handler()

    # ------------------------------------------------------------------
    # Window awareness callbacks
    # ------------------------------------------------------------------

    def on_window_opened(self, win: WindowInfo):
        pw = self._pw
        if pw._silent_mode or pw.pet.state == PetState.DRAGGED:
            return
        if pw._llm_enabled:
            if pw._llm_pending:
                return
            pw._llm_pending = True
            ctx = f"A new window just opened: '{win.title}'. React to it briefly."
            pw._llm.generate(ctx, pw._on_llm_response)
        else:
            comment = get_app_comment(win.title, pw.pet.name, process_name=win.process_name)
            if comment:
                pw._say(comment)

    def on_window_closed(self, win: WindowInfo):
        pw = self._pw
        if pw._silent_mode or pw.pet.state == PetState.DRAGGED:
            return
        if random.random() < 0.3:  # Don't always comment on closes
            if pw._llm_enabled:
                if pw._llm_pending:
                    return
                pw._llm_pending = True
                ctx = f"The window '{win.title}' just closed. React briefly."
                pw._llm.generate(ctx, pw._on_llm_response)
            else:
                pw._say(get_line("window_closed", pw.pet.name, app=win.title))

    # ------------------------------------------------------------------
    # Individual actions
    # ------------------------------------------------------------------

    def _do_comment(self):
        pw = self._pw
        windows = pw._window_awareness.get_interesting_windows()
        if not windows:
            return

        # 50% chance to comment on the foreground window if it's interesting
        fg = get_foreground_window()
        if fg and random.random() < 0.5:
            if not _is_junk_window(fg.title, fg.process_name):
                target = fg
            else:
                target = random.choice(windows)
        else:
            target = random.choice(windows)

        if pw._llm_enabled:
            if pw._llm_pending:
                return
            pw._llm_pending = True
            ctx = f"I just noticed a window: '{target.title}' ({target.process_name}). Comment on it."
            pw._llm.generate(ctx, pw._on_llm_response)
        else:
            comment = get_app_comment(
                target.title, pw.pet.name, process_name=target.process_name
            )
            if comment:
                pw._say(comment)

    def _do_push(self):
        pw = self._pw
        pushed = pw._window_awareness.try_push_window(
            pw.movement.x, pw.movement.y
        )
        if pushed:
            log.info("WIN_ACT push pos=(%d,%d)", pw.x(), pw.y())
            pw.pet.set_state(PetState.ATTACKING)
            pw._say(get_line("window_push", pw.pet.name))
            pw._temp_state_timer.start(2000)

    def _do_peek(self):
        pw = self._pw
        if pw.pet.state not in (PetState.IDLE, PetState.ATTACKING):
            return

        result = pw._window_awareness.get_peek_position(pw._sprite_size)
        if not result:
            return
        # Save position so we can return after the peek
        self._pre_peek_pos = (pw.movement.x, pw.movement.y)
        # Scale win32 coords to Qt logical coords
        s = pw.movement._dpi_scale
        peek_x = int(result["x"] / s)
        peek_y = int(result["y"] / s)
        log.info("WIN_ACT peek from=(%d,%d) to=(%d,%d) dpi=%.2f",
                 pw.x(), pw.y(), peek_x, peek_y, s)
        pw.pet.set_state(PetState.PEEKING)
        pw.movement.set_position(peek_x, peek_y)
        pw.move(pw.movement.x, pw.movement.y)
        pw._say(get_line("peeking", pw.pet.name))
        QTimer.singleShot(3000, self._return_from_peek)

    def _return_from_peek(self):
        """Restore pet to its pre-peek position so it doesn't get stranded."""
        if not self._pre_peek_pos:
            return
        pw = self._pw
        x, y = self._pre_peek_pos
        self._pre_peek_pos = None
        log.info("PEEK_RETURN to=(%d,%d) from pos=(%d,%d)", x, y, pw.x(), pw.y())
        pw.movement.set_position(x, y)
        pw.move(pw.movement.x, pw.movement.y)
        if pw.pet.state not in (PetState.DRAGGED, PetState.WALKING, PetState.RUNNING):
            pw.pet.set_state(PetState.IDLE)

    def _do_shake(self):
        pw = self._pw
        target = pw._window_awareness.try_shake_window(
            pw.movement.x, pw.movement.y
        )
        if not target:
            return
        log.info("WIN_ACT shake target='%s' pos=(%d,%d)", target.title, pw.x(), pw.y())
        pw.pet.set_state(PetState.ATTACKING)
        pw._say(get_line("window_shake", pw.pet.name))
        self._shake_hwnd = target.hwnd
        self._shake_step = 0
        self._shake_timer = QTimer()
        self._shake_timer.timeout.connect(self._on_shake_tick)
        self._shake_timer.start(50)

    def _on_shake_tick(self):
        pw = self._pw
        if not pw._window_awareness.do_shake_step(self._shake_hwnd, self._shake_step):
            self._shake_timer.stop()
            self._shake_timer.deleteLater()
            self._shake_timer = None
            pw._temp_state_timer.start(1000)
            return
        self._shake_step += 1

    def _do_minimize(self):
        pw = self._pw
        target = pw._window_awareness.try_minimize_window(
            pw.movement.x, pw.movement.y
        )
        if target:
            log.info("WIN_ACT minimize target='%s' pos=(%d,%d)", target.title, pw.x(), pw.y())
            pw.pet.set_state(PetState.ATTACKING)
            pw._say(get_line("window_minimize", pw.pet.name))
            pw._temp_state_timer.start(2000)

    def _do_sit(self):
        pw = self._pw
        if pw.pet.state not in (PetState.IDLE, PetState.ATTACKING):
            return
        result = pw._window_awareness.get_titlebar_position(pw._sprite_size)
        if not result:
            return
        # Scale win32 coords to Qt logical coords (matches platform coordinate space)
        s = pw.movement._dpi_scale
        sit_x = int(result["x"] / s)
        sit_y = int(result["y"] / s)
        log.info("WIN_ACT sit from=(%d,%d) to=(%d,%d) dpi=%.2f",
                 pw.x(), pw.y(), sit_x, sit_y, s)
        pw.movement.stop()
        pw.pet.set_state(PetState.IDLE)
        pw.movement.set_position(sit_x, sit_y)
        pw.move(pw.movement.x, pw.movement.y)
        pw._say(get_line("window_sit", pw.pet.name))
        pw._temp_state_timer.start(5000)

    def _do_resize(self):
        pw = self._pw
        target = pw._window_awareness.try_resize_window(
            pw.movement.x, pw.movement.y
        )
        if target:
            log.info("WIN_ACT resize target='%s' pos=(%d,%d)", target.title, pw.x(), pw.y())
            pw.pet.set_state(PetState.ATTACKING)
            pw._say(get_line("window_resize", pw.pet.name))
            pw._temp_state_timer.start(2000)

    def _do_knock(self):
        pw = self._pw
        target = pw._window_awareness.try_knock_window()
        if target:
            log.info("WIN_ACT knock target='%s' pos=(%d,%d)", target.title, pw.x(), pw.y())
            pw.pet.set_state(PetState.ATTACKING)
            pw._say(get_line("window_knock", pw.pet.name))
            pw._temp_state_timer.start(2000)

    def _do_drag(self):
        pw = self._pw
        if pw.pet.state not in (PetState.IDLE, PetState.ATTACKING):
            return
        target = pw._window_awareness.start_drag_window(
            pw.movement.x, pw.movement.y
        )
        if not target:
            return
        log.info("WIN_ACT drag target='%s' hwnd=%s pos=(%d,%d)",
                 target.title, target.hwnd, pw.x(), pw.y())
        self.dragging_window_hwnd = target.hwnd
        pw.pet.set_state(PetState.WALKING)
        pw.movement.pick_random_target()
        pw._say(get_line("window_drag", pw.pet.name))
        # Drag ends when the walk finishes (handled in PetWindow._on_move_tick)

    def _do_tidy(self):
        pw = self._pw
        success = pw._window_awareness.try_tidy_windows()
        if success:
            log.info("WIN_ACT tidy pos=(%d,%d)", pw.x(), pw.y())
            pw.pet.set_state(PetState.ATTACKING)
            pw._say(get_line("window_tidy", pw.pet.name))
            pw._temp_state_timer.start(3000)

    def _do_topple(self):
        pw = self._pw
        toppled = pw._window_awareness.try_topple_windows(
            pw.movement.x, pw.movement.y, pw.pet.direction
        )
        if toppled:
            log.info("WIN_ACT topple pos=(%d,%d) dir=%d",
                     pw.x(), pw.y(), pw.pet.direction)
            pw.pet.set_state(PetState.ATTACKING)
            pw._say(get_line("window_topple", pw.pet.name))
            pw._temp_state_timer.start(2500)
