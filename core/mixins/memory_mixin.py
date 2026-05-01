"""MemoryMixin — rolling conversation history for multi-turn LLM chat."""

import contextlib
import json
import logging
import os
import tempfile

from utils.paths import get_config_dir

log = logging.getLogger("pet_window")

_MEMORY_FILE = "memory.json"


class MemoryMixin:
    """Mixin that maintains a rolling list of user↔assistant message pairs.

    Each message is a dict with keys 'role' ('user' | 'assistant') and 'content'.
    The history is injected between the system prompt and the current user message
    in every LLM call that goes through _ask_direct_or_vision().
    """

    # ── Initialisation ────────────────────────────────────────────────────────

    def _init_memory(self) -> None:
        """Initialise the in-memory history list.  Call from PetWindow.__init__."""
        self._memory: list[dict] = []
        self._memory_max_turns: int = max(1, self._config.get("memory_max_turns", 5))
        self._memory_persist: bool = bool(self._config.get("memory_persist", False))
        if self._memory_persist:
            self._memory_load()
        log.debug(
            "Memory initialised: max_turns=%d persist=%s history=%d msgs",
            self._memory_max_turns,
            self._memory_persist,
            len(self._memory),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def _memory_add(self, role: str, content: str) -> None:
        """Append a message and trim history to the configured window."""
        if not content:
            return
        self._memory.append({"role": role, "content": content})
        max_msgs = self._memory_max_turns * 2
        if len(self._memory) > max_msgs:
            self._memory = self._memory[-max_msgs:]
        log.debug("Memory add role=%s len=%d", role, len(self._memory))
        if self._memory_persist:
            self._memory_save()

    def _memory_get_messages(self) -> list[dict]:
        """Return a shallow copy of the current history for LLM injection."""
        return list(self._memory)

    def _memory_clear(self) -> None:
        """Wipe conversation history (e.g. on mode change or manual reset)."""
        self._memory = []
        if self._memory_persist:
            self._memory_save()
        log.debug("Memory cleared")

    # ── Persistence ───────────────────────────────────────────────────────────

    def _memory_path(self) -> str:
        return os.path.join(get_config_dir(), _MEMORY_FILE)

    def _memory_load(self) -> None:
        path = self._memory_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                # Keep only valid message dicts
                self._memory = [
                    m for m in data
                    if isinstance(m, dict) and m.get("role") in ("user", "assistant")
                    and isinstance(m.get("content"), str)
                ]
                # Trim to current window size
                max_msgs = self._memory_max_turns * 2
                if len(self._memory) > max_msgs:
                    self._memory = self._memory[-max_msgs:]
                log.debug("Memory loaded %d msgs from %s", len(self._memory), path)
        except Exception as e:
            log.warning("Memory load failed (%s): %s", path, e)
            self._memory = []

    def _memory_save(self) -> None:
        path = self._memory_path()
        try:
            dir_ = os.path.dirname(path)
            os.makedirs(dir_, exist_ok=True)
            # Atomic write: write to a temp file, then replace
            fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._memory, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, path)
            except Exception:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise
        except Exception as e:
            log.warning("Memory save failed: %s", e)
