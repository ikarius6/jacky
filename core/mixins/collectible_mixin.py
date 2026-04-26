"""CollectibleMixin — collectible item spawning, collection, and persistence."""

import json
import random
import logging
import uuid
import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QTimer

from core.pet import PetState
from speech.dialogue import get_line
from utils.i18n import t, current_language

log = logging.getLogger("pet_window")

_COLLECTIBLES_DIR = Path(__file__).resolve().parent.parent.parent / "collectibles"

# System prompt for the spotted comment — keeps personality but avoids "mascota".
_SPOTTED_SYS_PROMPT = (
    "You are a playful chibi character living on a desktop. "
    "Speak in short, casual phrases (1-2 sentences). "
    "Be funny and intriguing. Use occasional emoticons like :3 or ^_^ "
    "Keep responses under 20 words. Respond in the SAME language as the user message."
)

# System prompt for card JSON generation — purely instructional, no personality.
_CARD_SYS_PROMPT = (
    "You are a creative JSON generator for a collectible card game. "
    "You generate fun, absurd, and creative content. "
    "Respond ONLY with valid JSON. No markdown, no extra text. "
    "NEVER use cats, pets, or animals as default themes."
)
_COLLECTION_PATH = _COLLECTIBLES_DIR / "collection.json"
_FALLBACKS_PATH = _COLLECTIBLES_DIR / "fallbacks.json"

# Spawn check every ~60 minutes via scheduler; 5% roll each time
_SPAWN_INTERVAL = (3400, 3800)  # seconds — roughly 1 hour
_SPAWN_CHANCE = 0.05

# Critical states where we should NOT spawn a collectible
_NO_SPAWN_STATES = frozenset({
    PetState.DRAGGED, PetState.HURT, PetState.DYING,
    PetState.ATTACKING, PetState.FALLING,
})


class CollectibleMixin:
    """Mixin providing collectible item spawning, LLM card generation, and persistence."""

    # ── Initialization ─────────────────────────────────────────────────────

    def _init_collectibles(self):
        """Load collection and register the hourly spawn check."""
        self._collection: list[dict] = self._load_collection()
        self._active_collectible = None  # CollectibleItemWidget or None
        self._active_card = None         # CollectibleCardDialog or None
        self._collectible_sprite_counts: dict[str, int] = {}
        self._collectible_enabled = self._config.get("collectibles_enabled", True)

        # Count times_seen per sprite from existing collection
        for c in self._collection:
            s = c.get("sprite", "")
            self._collectible_sprite_counts[s] = self._collectible_sprite_counts.get(s, 0) + 1

        # Register spawn check with the scheduler
        if self._collectible_enabled:
            self.scheduler.register("collectible_check", self._check_spawn_collectible, _SPAWN_INTERVAL)

    # ── Spawn check ────────────────────────────────────────────────────────

    def _check_spawn_collectible(self):
        """Called periodically (~1h). Roll dice and spawn if lucky."""
        if not self._collectible_enabled:
            return
        if self._active_collectible is not None:
            return
        if self._active_card is not None:
            return
        if self._silent_mode or self._gamer_mode:
            return
        if self.pet.state in _NO_SPAWN_STATES:
            return
        if self._boredom_asleep:
            return

        if random.random() < _SPAWN_CHANCE:
            self._spawn_collectible()

    def force_spawn_collectible(self):
        """Force-spawn a collectible (for testing / context menu)."""
        if self._active_collectible is not None:
            return
        if self._active_card is not None:
            return
        self._spawn_collectible()

    # ── Spawn ──────────────────────────────────────────────────────────────

    def _spawn_collectible(self):
        """Pick a random sprite, create the item widget, and show on screen."""
        from interaction.collectible_widgets import (
            CollectibleItemWidget, SPRITE_CATALOG, get_sprite_display_name
        )

        sprite_key = random.choice(list(SPRITE_CATALOG.keys()))
        display_name = get_sprite_display_name(sprite_key)

        # Pick a random position on screen (logical coords), avoiding the pet
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            sw, sh = geo.width(), geo.height()
            sx, sy = geo.x(), geo.y()
        else:
            sw, sh = 1920, 1080
            sx, sy = 0, 0

        margin = 80
        pet_x, pet_y = self.x(), self.y()
        for _ in range(20):
            x = random.randint(sx + margin, max(sx + margin + 1, sx + sw - margin))
            y = random.randint(sy + margin, max(sy + margin + 1, sy + sh - margin))
            if abs(x - pet_x) > 120 or abs(y - pet_y) > 120:
                break

        widget = CollectibleItemWidget(sprite_key, appearance_mode=self._appearance_mode)
        widget.clicked.connect(self._on_collectible_clicked)
        widget.spawn_at(x, y)
        self._active_collectible = widget

        # Clear reference when the widget auto-dismisses (fade-out done)
        widget._fade_out.finished.connect(self._on_collectible_dismissed)

        log.info("COLLECTIBLE spawned sprite=%s pos=(%d,%d) screen=(%d,%d) offset=(%d,%d)",
                 sprite_key, x, y, sw, sh, sx, sy)

        # Jacky comments about it
        if self._llm_enabled and not self._llm_pending:
            prompt = t("llm_prompts.collectible_spotted", sprite_name=display_name)
            ctx = f"Situation: {prompt}"
            self._llm_pending = True
            self._llm.generate(ctx, self._on_spotted_llm_response,
                               system_prompt=_SPOTTED_SYS_PROMPT)
        else:
            line = get_line("collectible_spotted", self.pet.name, sprite_name=display_name)
            if line:
                self._say(line)

    def _on_spotted_llm_response(self, text: str | None):
        """Thread-safe callback for the spotted comment."""
        self._llm_pending = False
        if text:
            self._llm_text_ready.emit(text)
        else:
            from interaction.collectible_widgets import get_sprite_display_name
            if self._active_collectible:
                display_name = get_sprite_display_name(self._active_collectible.sprite_key)
                line = get_line("collectible_spotted", self.pet.name, sprite_name=display_name) or "!"
                self._llm_text_ready.emit(line)

    def _on_collectible_dismissed(self):
        """Called when the collectible widget auto-dismisses (timeout/fade-out)."""
        log.info("COLLECTIBLE dismissed (timeout)")
        self._active_collectible = None

    # ── Collection ─────────────────────────────────────────────────────────

    def _on_collectible_clicked(self, sprite_key: str):
        """User clicked a collectible item. Generate the card."""
        self._active_collectible = None
        self._touch_user_interaction()
        self.pet.set_state(PetState.HAPPY)
        self._temp_state_timer.start(3000)

        from interaction.collectible_widgets import get_sprite_display_name
        display_name = get_sprite_display_name(sprite_key)

        # Bump times_seen
        self._collectible_sprite_counts[sprite_key] = (
            self._collectible_sprite_counts.get(sprite_key, 0) + 1
        )

        if self._llm_enabled and not self._llm_pending:
            self._show_thinking()
            self._llm_pending = True

            # Easter-egg prompt overrides
            # NOTE: use t() WITHOUT kwargs then .replace() — the prompt
            # contains JSON curly braces which break Python .format().
            if sprite_key == "jacky_plushie":
                prompt = t("llm_prompts.collectible_card_jacky")
            elif self._appearance_mode == "evil":
                prompt = t("llm_prompts.collectible_card_evil").replace("{sprite_name}", display_name)
            elif self._appearance_mode == "glitch":
                prompt = t("llm_prompts.collectible_card_glitch").replace("{sprite_name}", display_name)
            else:
                prompt = t("llm_prompts.collectible_card").replace("{sprite_name}", display_name)

            ctx = f"Situation: {prompt}"
            log.debug("COLLECTIBLE card prompt: %s", ctx[:300])

            def _on_card_response(text: str | None):
                self._llm_pending = False
                if text:
                    self._collectible_card_ready.emit(sprite_key, text)
                else:
                    self._collectible_card_ready.emit(sprite_key, "")

            self._llm.generate(ctx, _on_card_response,
                               system_prompt=_CARD_SYS_PROMPT)
        else:
            # No LLM — use fallback
            self._present_fallback_card(sprite_key)

    def _on_collectible_card_llm(self, sprite_key: str, raw_json: str):
        """Signal handler: process LLM card response on the main thread."""
        self._bubble.hide()
        if raw_json:
            card_data = self._parse_card_json(raw_json)
        else:
            card_data = None

        # Evil mode: force rarity 1 (common)
        if card_data and self._appearance_mode == "evil":
            card_data["rarity"] = 1

        if card_data:
            self._present_card(sprite_key, card_data)
        else:
            self._present_fallback_card(sprite_key)

    def _parse_card_json(self, text: str) -> Optional[dict]:
        """Try to parse the LLM card response as JSON."""
        import re
        # Strategy 1: direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Strategy 2: extract JSON block from markdown
        m = re.search(r'\{[^}]+\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        # Strategy 3: try cleaning common LLM quirks
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            inner = "\n".join(lines[1:-1]) if len(lines) > 2 else ""
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                pass
        log.warning("COLLECTIBLE card JSON parse failed: %s", text[:200])
        return None

    def _present_card(self, sprite_key: str, card_data: dict):
        """Show the collectible card UI with LLM-generated data."""
        from interaction.collectible_widgets import CollectibleCardDialog

        rarity = card_data.get("rarity", 1)
        if not isinstance(rarity, int) or rarity < 1 or rarity > 5:
            rarity = 1

        collectible = {
            "id": uuid.uuid4().hex[:8],
            "sprite": sprite_key,
            "name": str(card_data.get("name", "???"))[:60],
            "description": str(card_data.get("description", ""))[:300],
            "rarity": rarity,
            "obtained_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "times_seen": self._collectible_sprite_counts.get(sprite_key, 1),
        }

        # Position card near the pet
        cx = self.x() + self._sprite_size // 2
        card_x = cx - 160
        card_y = self.y() - 280

        card = CollectibleCardDialog(collectible, appearance_mode=self._appearance_mode)
        card.accepted.connect(self._on_card_accepted)
        card.dismissed.connect(self._on_card_dismissed)
        card.show_at(card_x, card_y)
        self._active_card = card

        line = get_line("collectible_collected", self.pet.name)
        if line:
            self._say(line)

    def _present_fallback_card(self, sprite_key: str):
        """Use fallback data when LLM is unavailable."""
        fallback_data = self._get_fallback()
        rarity = random.choice(fallback_data.get("rarity_pool", [1, 1, 2]))

        card_data = {
            "name": fallback_data.get("name", "???"),
            "description": fallback_data.get("description", ""),
            "rarity": rarity,
        }
        self._present_card(sprite_key, card_data)

    def _get_fallback(self) -> dict:
        """Load a random fallback from fallbacks.json."""
        try:
            with open(_FALLBACKS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            lang = current_language()
            pool = data.get(lang, data.get("en", []))
            if pool:
                return random.choice(pool)
        except Exception:
            log.warning("COLLECTIBLE fallbacks.json load failed", exc_info=True)
        return {"name": "???", "description": "...", "rarity_pool": [1]}

    def _on_card_accepted(self, collectible: dict):
        """User clicked "Add to collection" on the card."""
        self._active_card = None
        self._collection.append(collectible)
        self._save_collection()
        log.info("COLLECTIBLE saved id=%s name='%s' rarity=%d",
                 collectible.get("id"), collectible.get("name"), collectible.get("rarity"))

        line = get_line("collectible_added", self.pet.name)
        if line:
            self._say(line)

    def _on_card_dismissed(self):
        """User dismissed the card without adding it."""
        self._active_card = None
        log.info("COLLECTIBLE card dismissed by user")

    def _on_collectible_deleted(self, cid: str):
        """User deleted a collectible from the collection panel."""
        self._save_collection()
        log.info("COLLECTIBLE deleted id=%s, remaining=%d", cid, len(self._collection))

    # ── Persistence ────────────────────────────────────────────────────────

    def _load_collection(self) -> list:
        """Read collection.json, return list of collectibles."""
        if not _COLLECTION_PATH.exists():
            return []
        try:
            with open(_COLLECTION_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("collectibles", [])
        except Exception:
            log.warning("COLLECTIBLE collection.json load failed", exc_info=True)
            return []

    def _save_collection(self):
        """Write collection.json atomically."""
        import os
        _COLLECTIBLES_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "total_found": len(self._collection),
            "collectibles": self._collection,
        }
        tmp = _COLLECTION_PATH.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(str(tmp), str(_COLLECTION_PATH))
        except Exception:
            log.error("COLLECTIBLE save failed", exc_info=True)

    # ── Cleanup ────────────────────────────────────────────────────────────

    def _cleanup_collectibles(self):
        """Called on quit — dismiss any active item or card."""
        if self._active_collectible is not None:
            try:
                self._active_collectible.hide()
                self._active_collectible.deleteLater()
            except Exception:
                pass
            self._active_collectible = None
        if self._active_card is not None:
            try:
                self._active_card.hide()
                self._active_card.deleteLater()
            except Exception:
                pass
            self._active_card = None
