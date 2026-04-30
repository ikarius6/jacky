"""Main handler that orchestrates the screen interaction flow.

Capture → LLM grid-locate → walk → refine → execute.
"""

import json
import logging
import re
import time
from typing import Optional, Tuple

from PyQt6.QtCore import QTimer, pyqtSignal, QObject
from PyQt6.QtWidgets import QApplication

from speech.dialogue import get_line
from utils.i18n import (
    get_interact_keywords,
    get_interact_system_prompt,
    get_interact_grid_prompt,
    get_interact_locate_prompt,
    get_interact_refine_prompt,
    get_type_separators,
)
from utils.screen_capture import capture_full_screen_gridded, encode_qimage_png, capture_vision_area, draw_subgrid
from pal import click_at, send_alt_f4, minimize_foreground_window, type_text

from core.screen_interaction.constants import (
    CONFIDENCE_THRESHOLD,
    TASK_TIMEOUT_MS,
    GRID_COLS,
    GRID_ROWS,
    SUB_COLS,
    SUB_ROWS,
)
from core.screen_interaction.debug import save_b64, save_qimage, mark_point, mark_cell, set_enabled as _set_debug_enabled
from core.screen_interaction.task import ScreenInteractionTask

log = logging.getLogger("screen_interaction")


class ScreenInteractionHandler(QObject):
    """Orchestrates the screen interaction flow: capture → LLM locate → walk → refine → execute."""

    # Signals for thread-safe LLM callback delivery
    _grid_ready = pyqtSignal(str)
    _locate_ready = pyqtSignal(str)
    _refine_ready = pyqtSignal(str)

    def __init__(self, pet_window):
        super().__init__(pet_window)
        self._pet = pet_window
        _set_debug_enabled(self._pet._config.get("debug_logging", False))
        self._current_task: Optional[ScreenInteractionTask] = None

        self._safety_timer = QTimer(self)
        self._safety_timer.setSingleShot(True)
        self._safety_timer.timeout.connect(self._on_timeout)

        self._grid_ready.connect(self._on_grid_response)
        self._locate_ready.connect(self._on_locate_response)
        self._refine_ready.connect(self._on_refine_response)

        # State for two-phase locate (grid → crop)
        self._clean_qimage = None
        self._cell_dims = (0.0, 0.0)
        self._crop_offset = (0, 0)
        self._crop_size = (0, 0)
        self._sub_grid_dims = (3, 3, 0.0, 0.0)

    # ── Window visibility helpers ─────────────────────────────────

    def _hide_pet_windows(self):
        """Hide the pet sprite and speech bubble so they don't appear in captures."""
        self._pet._bubble.hide()
        self._pet.hide()
        # Process events and wait so Windows repaints the area behind the widgets
        QApplication.processEvents()
        time.sleep(0.15)

    def _show_pet_windows(self):
        """Restore the pet sprite and speech bubble after capture."""
        self._pet.show()
        self._pet._remove_dwm_border()
        self._pet._reassert_topmost()

    # ── Public API ────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """True if there is an in-progress task."""
        if self._current_task is None:
            return False
        return self._current_task.state not in ("done", "failed", "cancelled")

    def _get_prep_pattern(self) -> re.Pattern:
        from utils.i18n import current_language, get_interact_prefixes
        
        lang = current_language()
        if getattr(self, "_last_lang", None) == lang and getattr(self, "_cached_prep_pattern", None) is not None:
            return self._cached_prep_pattern
            
        prefixes = get_interact_prefixes()
        if not prefixes:
            self._cached_prep_pattern = re.compile(r"^")
        else:
            sorted_prefixes = sorted(prefixes, key=len, reverse=True)
            escaped = [re.escape(p) for p in sorted_prefixes]
            pattern_str = r"^(?:(?:" + r"|".join(escaped) + r")\s+)+"
            self._cached_prep_pattern = re.compile(pattern_str, re.IGNORECASE)
            
        self._last_lang = lang
        return self._cached_prep_pattern

    def try_parse_interaction(self, text: str) -> Optional[Tuple[str, str, Optional[str]]]:
        """Parse user text for interaction keywords from i18n.

        Returns ``(action_type, target_description, type_text)`` or ``None``.
        *type_text* is ``None`` for all actions except ``"type"``.
        Priority order: close > minimize > type > click > navigate.
        """
        lower = text.lower().strip()
        kw_map = get_interact_keywords()
        if not kw_map:
            return None

        prep_pattern = self._get_prep_pattern()

        for action_type in ("close", "minimize", "type", "click", "navigate"):
            keywords = kw_map.get(action_type, [])
            for kw in sorted(keywords, key=len, reverse=True):
                kw_lower = kw.lower()

                # --- Match at start of text ---
                if lower.startswith(kw_lower):
                    remainder = text[len(kw):].strip()
                    if action_type == "type":
                        result = self._parse_type_remainder(remainder)
                        if result:
                            return ("type", result[1], result[0])
                    else:
                        raw_target = remainder.strip("\"'").strip()
                        target = prep_pattern.sub("", raw_target).strip()
                        if target:
                            return (action_type, target, None)

                # --- Match anywhere in text ---
                idx = lower.find(kw_lower)
                if idx != -1:
                    remainder = text[idx + len(kw):].strip()
                    if action_type == "type":
                        result = self._parse_type_remainder(remainder)
                        if result:
                            return ("type", result[1], result[0])
                    else:
                        raw_target = remainder.strip("\"'").strip()
                        target = prep_pattern.sub("", raw_target).strip()
                        if target:
                            return (action_type, target, None)

        return None

    def _parse_type_remainder(self, remainder: str) -> Optional[Tuple[str, str]]:
        """Extract (text_to_type, target) from the text after a 'type' keyword.

        Supports two formats:
        1. Quoted text: ``'"hello world" in the search bar'``
        2. Unquoted text: ``'hello world in the search bar'``
           → splits on the **last** occurrence of a separator word.

        Returns ``(text_to_type, target)`` or ``None`` if unparseable.
        """
        prep_pattern = self._get_prep_pattern()
        separators = get_type_separators()

        # 1. Try quoted text: "..." or '...'
        quote_match = re.match(r'''["'](.+?)["']\s*(.*)''', remainder)
        if quote_match:
            text_to_type = quote_match.group(1).strip()
            after_quote = quote_match.group(2).strip()
            if text_to_type and after_quote:
                # Strip separator from the start of after_quote to get target
                target = self._strip_leading_separator(after_quote, separators)
                target = prep_pattern.sub("", target).strip()
                if target:
                    return (text_to_type, target)

        # 2. Unquoted text — find the LAST separator to split
        lower_rem = remainder.lower()
        best_pos = -1
        best_sep_len = 0
        for sep in separators:
            sep_lower = sep.lower()
            # Find as whole word (space-bounded or at end)
            search_start = 0
            while True:
                pos = lower_rem.find(sep_lower, search_start)
                if pos == -1:
                    break
                # Ensure word boundary: preceded by space (or start) and followed by space (or end)
                before_ok = (pos == 0 or lower_rem[pos - 1] == ' ')
                after_end = pos + len(sep_lower)
                after_ok = (after_end >= len(lower_rem) or lower_rem[after_end] == ' ')
                if before_ok and after_ok and pos > best_pos:
                    best_pos = pos
                    best_sep_len = len(sep_lower)
                search_start = pos + 1

        if best_pos > 0:
            text_to_type = remainder[:best_pos].strip().strip("\"'").strip()
            target = remainder[best_pos + best_sep_len:].strip()
            target = prep_pattern.sub("", target).strip()
            if text_to_type and target:
                return (text_to_type, target)

        return None

    @staticmethod
    def _strip_leading_separator(text: str, separators: list) -> str:
        """Remove a single leading separator word from *text*."""
        lower = text.lower()
        for sep in separators:  # already sorted longest-first
            sep_lower = sep.lower()
            if lower.startswith(sep_lower):
                after = text[len(sep_lower):]
                if not after or after[0] == ' ':
                    return after.strip()
        return text

    def start_task(self, action_type: str, target_desc: str,
                    type_text_content: Optional[str] = None):
        """Begin the full interaction sequence."""
        log.info("START_TASK action=%s target=%r type_text=%r",
                 action_type, target_desc, type_text_content[:60] if type_text_content else None)
        self._current_task = ScreenInteractionTask(
            action_type=action_type,
            target_desc=target_desc,
            state="locating",
            type_text=type_text_content,
        )
        # Say acknowledgment
        line = get_line("interact_ack", self._pet.pet.name)
        self._pet._say(line, force=True)

        # Start safety timer
        self._safety_timer.start(TASK_TIMEOUT_MS)

        # Begin capture and locate
        self._step_capture_and_locate()

    def cancel(self, say_line: bool = True):
        """Cancel the current task."""
        if not self.is_active:
            return
        log.info("CANCEL_TASK state=%s", self._current_task.state)
        self._current_task.state = "cancelled"
        self._safety_timer.stop()
        self._pet._llm_pending = False
        self._clean_qimage = None
        if say_line:
            line = get_line("interact_cancelled", self._pet.pet.name)
            self._pet._say(line, force=True)

    def on_arrival(self):
        """Called by pet_window._on_move_tick when the pet arrives at the target coords.

        Decides whether to refine or execute.
        """
        if not self.is_active or self._current_task.state != "moving":
            return
        log.info("ARRIVAL confidence=%d", self._current_task.confidence)
        if self._current_task.confidence >= CONFIDENCE_THRESHOLD:
            # High confidence — skip refinement, go straight to execute
            self._step_execute()
        else:
            # Low confidence — refine with local vision
            self._current_task.state = "refining"
            self._step_refine()

    # ── Phase 1: Grid capture & locate ────────────────────────────

    def _step_capture_and_locate(self):
        """Phase 1: Full screen capture with numbered grid → LLM identifies which cell."""
        if not self.is_active:
            return
        # Hide pet UI so the request text doesn't pollute the screenshot
        self._hide_pet_windows()
        try:
            grid_b64, clean_qimg, orig_size, scale_factor, cell_dims = \
                capture_full_screen_gridded(cols=GRID_COLS, rows=GRID_ROWS)
            self._current_task.scale_factor = scale_factor
            self._current_task.original_size = orig_size
            self._clean_qimage = clean_qimg
            self._cell_dims = cell_dims
            # Debug: save what we send to the LLM
            save_b64(grid_b64, "01_grid_sent.png")
            save_qimage(clean_qimg, "00_clean_full.png")
        except Exception as e:
            log.error("capture_full_screen_gridded failed: %s", e)
            self._show_pet_windows()
            self._fail("interact_not_found")
            return
        finally:
            self._show_pet_windows()

        total = GRID_COLS * GRID_ROWS
        system_prompt = get_interact_system_prompt()
        grid_template = get_interact_grid_prompt()
        if not grid_template:
            grid_template = (
                'The image has a numbered grid overlay ({cols} columns x {rows} rows). '
                'Cells numbered 1 to {total}, left to right, top to bottom. '
                'Which cell contains: "{target}"? Also identify the second-best candidate '
                'cell if the target is near a cell boundary. '
                'Respond ONLY with JSON: {{"cell": <number>, "confidence": <0_to_100>, '
                '"alt_cell": <second_best_number_or_null>}}. '
                'If not visible: {{"error": "not found"}}'
            )
        user_prompt = (grid_template
                       .replace("{target}", self._current_task.target_desc)
                       .replace("{cols}", str(GRID_COLS))
                       .replace("{rows}", str(GRID_ROWS))
                       .replace("{total}", str(total)))

        self._pet._llm_pending = True
        self._pet._show_thinking()

        def _callback(text):
            self._grid_ready.emit(text if text else "")

        self._pet._llm.generate_with_image(
            user_prompt, grid_b64, _callback, system_prompt=system_prompt
        )

    def _on_grid_response(self, raw_text: str):
        """Handle grid-cell identification (phase 1).  Crops the cell and fires phase 2."""
        if not self.is_active or self._current_task.state != "locating":
            self._pet._llm_pending = False
            self._clean_qimage = None
            return

        if not raw_text:
            self._pet._llm_pending = False
            self._pet._bubble.hide()
            self._clean_qimage = None
            self._fail("interact_not_found")
            return

        parsed = self._parse_llm_json(raw_text)
        if not parsed or "error" in parsed:
            log.info("GRID not found or parse error: %r", raw_text[:200])
            self._pet._llm_pending = False
            self._pet._bubble.hide()
            self._clean_qimage = None
            self._fail("interact_not_found")
            return

        try:
            cell_num = int(parsed["cell"])
            confidence = int(parsed.get("confidence", 50))
        except (KeyError, ValueError, TypeError):
            log.warning("GRID invalid JSON fields: %r", parsed)
            self._pet._llm_pending = False
            self._pet._bubble.hide()
            self._clean_qimage = None
            self._fail("interact_not_found")
            return

        total = GRID_COLS * GRID_ROWS
        if cell_num < 1 or cell_num > total:
            log.warning("GRID cell=%d out of range [1,%d]", cell_num, total)
            self._pet._llm_pending = False
            self._pet._bubble.hide()
            self._clean_qimage = None
            self._fail("interact_not_found")
            return

        # Persist Phase 1 confidence for dynamic crop sizing in Phase 2
        self._current_task.confidence = confidence

        # Parse optional alternative cell candidate
        alt_cell_num = None
        try:
            raw_alt = parsed.get("alt_cell")
            if raw_alt is not None:
                alt_cell_num = int(raw_alt)
                if alt_cell_num < 1 or alt_cell_num > total:
                    alt_cell_num = None
        except (ValueError, TypeError):
            alt_cell_num = None

        cell_w, cell_h = self._cell_dims
        col = (cell_num - 1) % GRID_COLS
        row = (cell_num - 1) // GRID_COLS
        center_x = col * cell_w + cell_w / 2
        center_y = row * cell_h + cell_h / 2

        log.info("GRID cell=%d col=%d row=%d center=(%.0f,%.0f) conf=%d alt=%s",
                 cell_num, col, row, center_x, center_y, confidence, alt_cell_num)

        # Debug: highlight selected cell
        mark_cell("01_grid_sent.png", "02_grid_result.png",
                  cell_num, GRID_COLS, GRID_ROWS, cell_w, cell_h)

        # Phase 2: crop around the identified cell and ask for precise coords
        self._step_crop_and_locate(center_x, center_y, cell_w, cell_h, alt_cell_num)

    # ── Phase 2: Crop & sub-grid locate ───────────────────────────

    def _step_crop_and_locate(self, center_x: float, center_y: float,
                               cell_w: float, cell_h: float,
                               alt_cell_num: int = None):
        """Phase 2: Crop around identified cell, overlay a sub-grid → LLM picks sub-cell.

        Uses the **same grid-classification approach** as Phase 1 (which cell
        contains the target?) rather than asking for coordinates — LLMs are
        reliable at classification but terrible at coordinate estimation.

        Dynamic crop sizing: the padding factor grows when Phase 1 confidence
        is low, and the crop center shifts toward the midpoint between the
        primary and alternative cells when they are adjacent.
        """
        if self._clean_qimage is None:
            self._pet._llm_pending = False
            self._pet._bubble.hide()
            self._fail("interact_not_found")
            return

        clean = self._clean_qimage
        img_w = clean.width()
        img_h = clean.height()

        # Dynamic crop: wider context when Phase 1 confidence is low
        confidence = self._current_task.confidence
        if confidence < 50:
            padding_factor = 3.0   # include ±1 adjacent cells
        elif confidence < 60:
            padding_factor = 2.5
        else:
            padding_factor = 2.0

        # If the LLM provided an adjacent alt_cell, shift crop center
        # toward the midpoint between the two candidates
        crop_center_x = center_x
        crop_center_y = center_y
        if alt_cell_num is not None and confidence < 80:
            alt_col = (alt_cell_num - 1) % GRID_COLS
            alt_row = (alt_cell_num - 1) // GRID_COLS
            alt_cx = alt_col * cell_w + cell_w / 2
            alt_cy = alt_row * cell_h + cell_h / 2
            # Check adjacency: ≤ 1 cell apart in both axes
            if abs(alt_col - (int(center_x // cell_w))) <= 1 and \
               abs(alt_row - (int(center_y // cell_h))) <= 1:
                # Shift center 30% toward alt candidate (bias toward primary)
                crop_center_x = center_x * 0.7 + alt_cx * 0.3
                crop_center_y = center_y * 0.7 + alt_cy * 0.3
                # Ensure crop is wide enough to cover both cells
                padding_factor = max(padding_factor, 2.5)
                log.info("CROP alt_cell=%d adjacent, center shifted "
                         "(%.0f,%.0f)->(%.0f,%.0f) pad=%.1f",
                         alt_cell_num, center_x, center_y,
                         crop_center_x, crop_center_y, padding_factor)

        log.info("CROP padding=%.1fx conf=%d", padding_factor, confidence)

        crop_w = int(cell_w * padding_factor)
        crop_h = int(cell_h * padding_factor)
        crop_left = max(0, int(crop_center_x - crop_w / 2))
        crop_top = max(0, int(crop_center_y - crop_h / 2))
        if crop_left + crop_w > img_w:
            crop_left = max(0, img_w - crop_w)
        if crop_top + crop_h > img_h:
            crop_top = max(0, img_h - crop_h)
        crop_w = min(crop_w, img_w - crop_left)
        crop_h = min(crop_h, img_h - crop_top)

        cropped = clean.copy(crop_left, crop_top, crop_w, crop_h)
        self._clean_qimage = None  # free memory

        # Debug: save the clean crop (before sub-grid)
        save_qimage(cropped, "03_crop_sent.png")

        self._crop_offset = (crop_left, crop_top)
        self._crop_size = (crop_w, crop_h)

        # Draw sub-grid overlay for precise classification
        sub_cols, sub_rows = SUB_COLS, SUB_ROWS
        gridded, sub_cell_w, sub_cell_h = draw_subgrid(cropped, sub_cols, sub_rows)
        self._sub_grid_dims = (sub_cols, sub_rows, sub_cell_w, sub_cell_h)

        save_qimage(gridded, "03b_crop_gridded.png")

        crop_b64 = encode_qimage_png(gridded)
        log.debug("CROP offset=(%d,%d) size=%dx%d subgrid=%dx%d",
                  crop_left, crop_top, crop_w, crop_h, sub_cols, sub_rows)

        # Ask LLM the same type of question as Phase 1: "which cell?"
        total = sub_cols * sub_rows
        system_prompt = get_interact_system_prompt()
        locate_template = get_interact_locate_prompt()
        if not locate_template:
            locate_template = (
                'This zoomed-in image has a green numbered grid overlay '
                '({cols} columns x {rows} rows). Cells numbered 1 to {total}, '
                'left to right, top to bottom. '
                'First, describe in one sentence what you see in the image. '
                'Which cell contains the CENTER of: "{target}"? '
                'Respond ONLY with JSON: {{"cell": <number>, "confidence": <0_to_100>}}. '
                'If not found: {{"error": "not found"}}'
            )
        user_prompt = (locate_template
                       .replace("{target}", self._current_task.target_desc)
                       .replace("{cols}", str(sub_cols))
                       .replace("{rows}", str(sub_rows))
                       .replace("{total}", str(total))
                       .replace("{width}", str(crop_w))
                       .replace("{height}", str(crop_h)))

        def _callback(text):
            self._locate_ready.emit(text if text else "")

        self._pet._llm.generate_with_image(
            user_prompt, crop_b64, _callback, system_prompt=system_prompt
        )

    def _on_locate_response(self, raw_text: str):
        """Handle sub-cell classification (phase 2, runs on main thread).

        The LLM returns a sub-cell number (same format as Phase 1).
        We compute the center of that sub-cell and map it through
        crop → resized → physical → Qt logical coordinates.
        """
        self._pet._llm_pending = False
        self._pet._bubble.hide()
        self._clean_qimage = None  # safety

        if not self.is_active or self._current_task.state != "locating":
            return

        if not raw_text:
            self._fail("interact_not_found")
            return

        parsed = self._parse_llm_json(raw_text)
        if parsed is None:
            log.warning("Could not parse locate JSON from: %r", raw_text[:200])
            self._fail("interact_not_found")
            return

        if "error" in parsed:
            log.info("LLM said element not found: %s", parsed["error"])
            self._fail("interact_not_found")
            return

        try:
            sub_cell = int(parsed["cell"])
            confidence = int(parsed.get("confidence", 50))
        except (KeyError, ValueError, TypeError) as e:
            log.warning("Invalid locate JSON fields: %s — parsed=%r", e, parsed)
            self._fail("interact_not_found")
            return

        confidence = max(0, min(100, confidence))

        sub_cols, sub_rows, sub_cell_w, sub_cell_h = self._sub_grid_dims
        total = sub_cols * sub_rows
        if sub_cell < 1 or sub_cell > total:
            log.warning("SUB-GRID cell=%d out of range [1,%d]", sub_cell, total)
            self._fail("interact_not_found")
            return

        # Sub-cell center within the crop
        sc = (sub_cell - 1) % sub_cols
        sr = (sub_cell - 1) // sub_cols
        crop_x = sc * sub_cell_w + sub_cell_w / 2
        crop_y = sr * sub_cell_h + sub_cell_h / 2

        # Map crop coords → resized-image coords
        offset_x, offset_y = self._crop_offset
        resized_x = crop_x + offset_x
        resized_y = crop_y + offset_y

        # Resized → physical screen coords
        scale = self._current_task.scale_factor
        phys_x = int(resized_x * scale)
        phys_y = int(resized_y * scale)

        # Physical → Qt logical coords
        screen = self._pet._current_screen()
        dpi = screen.devicePixelRatio() if screen else 1.0
        qt_x = int(phys_x / dpi)
        qt_y = int(phys_y / dpi)

        self._current_task.target_coords = (qt_x, qt_y)
        self._current_task.confidence = confidence
        self._current_task.state = "moving"

        log.info("LOCATE sub_cell=%d crop_px=(%.0f,%.0f) resized=(%.0f,%.0f) "
                 "phys=(%d,%d) qt=(%d,%d) conf=%d",
                 sub_cell, crop_x, crop_y, resized_x, resized_y,
                 phys_x, phys_y, qt_x, qt_y, confidence)

        # Debug: mark on crop and full-screen images
        mark_point("03_crop_sent.png", "04_crop_result.png",
                   crop_x, crop_y,
                   f"sub={sub_cell} px=({crop_x:.0f},{crop_y:.0f})")
        mark_point("00_clean_full.png", "05_fullscreen_result.png",
                   resized_x, resized_y,
                   f"resized=({resized_x:.0f},{resized_y:.0f}) qt=({qt_x},{qt_y})")

        line = get_line("interact_found", self._pet.pet.name)
        self._pet._say(line, force=True)
        self._pet._move_to_screen_target(qt_x, qt_y)

    # ── Phase 3: Refine ──────────────────────────────────────────

    def _step_refine(self):
        """Step 3 (optional): Local 1024×1024 capture → LLM refine position."""
        if not self.is_active:
            return

        screen = self._pet._current_screen()
        dpi = screen.devicePixelRatio() if screen else 1.0
        cx = self._pet.x() + self._pet._sprite_size // 2
        cy = self._pet.y() + self._pet._sprite_size // 2

        # Hide pet UI so it doesn't appear in the refinement capture
        self._hide_pet_windows()
        try:
            image_b64 = capture_vision_area(cx, cy, dpi_scale=dpi)
        except Exception as e:
            log.error("capture_vision_area failed during refine: %s", e)
            self._show_pet_windows()
            # Skip refine, just execute
            self._step_execute()
            return
        self._show_pet_windows()

        system_prompt = get_interact_system_prompt()
        refine_template = get_interact_refine_prompt()
        if not refine_template:
            refine_template = (
                'You are looking at a 1024x1024 area of the screen centered on a point. '
                'Can you see "{target}"? If yes, how far is it from the center? '
                'Respond ONLY with JSON: {{"found": true, "offset_x": <pixels_from_center>, '
                '"offset_y": <pixels_from_center>}}. If not found: {{"found": false}}'
            )
        user_prompt = refine_template.replace("{target}", self._current_task.target_desc)

        self._pet._llm_pending = True
        self._pet._show_thinking()

        def _callback(text):
            if text:
                self._refine_ready.emit(text)
            else:
                self._refine_ready.emit("")

        self._pet._llm.generate_with_image(
            user_prompt, image_b64, _callback, system_prompt=system_prompt
        )

    def _on_refine_response(self, raw_text: str):
        """Handle the LLM refine response (runs on main thread via signal)."""
        self._pet._llm_pending = False
        self._pet._bubble.hide()

        if not self.is_active or self._current_task.state != "refining":
            return

        if raw_text:
            parsed = self._parse_llm_json(raw_text)
            if parsed and parsed.get("found"):
                try:
                    offset_x = int(parsed.get("offset_x", 0))
                    offset_y = int(parsed.get("offset_y", 0))
                    if abs(offset_x) > 10 or abs(offset_y) > 10:
                        # Significant offset — adjust target and walk a bit more
                        screen = self._pet._current_screen()
                        dpi = screen.devicePixelRatio() if screen else 1.0
                        qt_ox = int(offset_x / dpi)
                        qt_oy = int(offset_y / dpi)
                        old_x, old_y = self._current_task.target_coords
                        new_x = old_x + qt_ox
                        new_y = old_y + qt_oy
                        self._current_task.target_coords = (new_x, new_y)
                        log.info("REFINE adjusted by (%d,%d) -> (%d,%d)", qt_ox, qt_oy, new_x, new_y)
                        # Walk to the refined position
                        self._current_task.state = "moving"
                        self._current_task.confidence = 95  # after refine, trust is high
                        self._pet._move_to_screen_target(new_x, new_y)
                        return
                except (ValueError, TypeError):
                    pass

        # No significant adjustment needed or parse failed — just execute
        self._step_execute()

    # ── Phase 4: Execute ─────────────────────────────────────────

    def _step_execute(self):
        """Step 4: Execute the action based on action_type."""
        if not self.is_active:
            return
        self._current_task.state = "executing"
        self._safety_timer.stop()
        task = self._current_task

        if task.action_type == "navigate":
            # Just arrived — say done
            self._complete("interact_done_navigate")
            return

        # For click/close/minimize/type — need to do the actual action
        # Play attack animation first
        from core.pet import PetState
        self._pet.pet.set_state(PetState.ATTACKING)

        # Delay the actual click to let the animation play
        QTimer.singleShot(500, self._do_action)

    def _do_action(self):
        """Actually perform the click/close/minimize action."""
        if not self.is_active or self._current_task.state != "executing":
            return
        task = self._current_task

        # Convert Qt logical coords to physical screen coords for the click
        screen = self._pet._current_screen()
        dpi = screen.devicePixelRatio() if screen else 1.0
        qt_x, qt_y = task.target_coords
        phys_x = int(qt_x * dpi)
        phys_y = int(qt_y * dpi)

        # Make the pet transparent to clicks so it doesn't click itself
        self._pet.set_click_through(True)

        if task.action_type == "click":
            success = click_at(phys_x, phys_y, safety_check=True)
            self._pet.set_click_through(False)
            if success:
                self._complete("interact_done_action")
            else:
                log.warning("click_at aborted (safety check)")
                line = get_line("interact_click_aborted", self._pet.pet.name)
                self._pet._say(line, force=True)
                self._current_task.state = "failed"
                from core.pet import PetState
                self._pet.pet.set_state(PetState.ERROR)

        elif task.action_type == "close":
            # Click to bring window to foreground, then Alt+F4
            click_at(phys_x, phys_y, safety_check=True)
            self._pet.set_click_through(False)
            QTimer.singleShot(300, self._do_close)

        elif task.action_type == "minimize":
            # Click to bring window to foreground, then minimize
            click_at(phys_x, phys_y, safety_check=True)
            self._pet.set_click_through(False)
            QTimer.singleShot(300, self._do_minimize)

        elif task.action_type == "type":
            # Click to focus the target element, then type the text
            success = click_at(phys_x, phys_y, safety_check=True)
            self._pet.set_click_through(False)
            if success:
                # Small delay for the element to gain focus before typing
                QTimer.singleShot(400, self._do_type)
            else:
                log.warning("type: click_at aborted (safety check)")
                line = get_line("interact_click_aborted", self._pet.pet.name)
                self._pet._say(line, force=True)
                self._current_task.state = "failed"
                from core.pet import PetState
                self._pet.pet.set_state(PetState.ERROR)

    def _do_close(self):
        """Send Alt+F4 after clicking on the target."""
        send_alt_f4()
        self._complete("interact_done_action")

    def _do_minimize(self):
        """Minimize the foreground window after clicking on the target."""
        minimize_foreground_window()
        self._complete("interact_done_action")

    def _do_type(self):
        """Type the stored text after the target element has been clicked/focused."""
        if not self.is_active or self._current_task.state != "executing":
            return
        text = self._current_task.type_text
        
        if text:
            from core.pet import PetState
            self._pet.pet.set_state(PetState.TYPING)
            
            import threading
            from PyQt6.QtCore import QTimer
            
            def _type_bg():
                type_text(text)
                QTimer.singleShot(0, lambda: self._complete("interact_done_type"))
                
            threading.Thread(target=_type_bg, daemon=True).start()
        else:
            self._complete("interact_done_type")

    # ── Helpers ───────────────────────────────────────────────────

    def _complete(self, dialogue_key: str):
        """Mark task as done and say completion line."""
        if self._current_task:
            self._current_task.state = "done"
        self._safety_timer.stop()
        from core.pet import PetState
        self._pet.pet.set_state(PetState.IDLE)
        line = get_line(dialogue_key, self._pet.pet.name)
        self._pet._say(line, force=True)

    def _fail(self, dialogue_key: str):
        """Mark task as failed and say failure line."""
        if self._current_task:
            self._current_task.state = "failed"
        self._safety_timer.stop()
        self._pet._llm_pending = False
        self._clean_qimage = None
        from core.pet import PetState
        if dialogue_key == "interact_not_found":
            self._pet.pet.set_state(PetState.CONFUSED)
        else:
            self._pet.pet.set_state(PetState.ERROR)
        line = get_line(dialogue_key, self._pet.pet.name)
        self._pet._say(line, force=True)

    def _on_timeout(self):
        """Safety net: cancel task after timeout."""
        if self.is_active:
            log.warning("TIMEOUT task state=%s", self._current_task.state)
            self._current_task.state = "failed"
            self._pet._llm_pending = False
            self._clean_qimage = None
            from core.pet import PetState
            self._pet.pet.set_state(PetState.ERROR)
            line = get_line("interact_timeout", self._pet.pet.name)
            self._pet._say(line, force=True)

    @staticmethod
    def _parse_llm_json(raw_text: str) -> Optional[dict]:
        r"""Extract JSON from LLM response, tolerating markdown fences, think tags, extra text.

        Tries in order:
        1. ``json.loads(stripped text)``
        2. Regex: content inside triple-backtick json fences
        3. Regex: first ``{...}`` block in the text
        Returns parsed dict or ``None``.
        """
        # Strip think tags first
        text = re.sub(r"<think>[\s\S]*?</think>", "", raw_text).strip()

        # 1. Try direct parse
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

        # 2. Try markdown json fence
        fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", text)
        if fence_match:
            try:
                result = json.loads(fence_match.group(1).strip())
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, ValueError):
                pass

        # 3. Try first {...} block
        brace_match = re.search(r"\{[^{}]*\}", text)
        if brace_match:
            try:
                result = json.loads(brace_match.group(0))
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, ValueError):
                pass

        return None
