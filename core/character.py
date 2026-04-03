"""
Character auto-discovery — scans sprites/*/character.json to register characters.

Each sprite pack needs a small ``character.json`` next to its frames::

    {
        "name": "Forest Ranger 1",
        "sprite_size": 128,
        "fps": 10
    }

For ``sequence_dirs`` packs the state_map and flip_states are **auto-detected**
from the subdirectory names using DIR_TO_STATES.  You can still supply explicit
``state_map`` / ``flip_states`` / ``type`` in the JSON to override.

For ``flat`` packs (like placeholder) set ``"type": "flat"`` in the JSON.
"""

import json
import logging
import os

from utils.paths import get_data_dir

log = logging.getLogger(__name__)

BASE_DIR = get_data_dir()
SPRITES_ROOT = os.path.join(BASE_DIR, "sprites")

# ── standard directory-name → internal-state(s) mapping ────────────────
# Each entry maps a sprite subdirectory name to one or more internal states.
DIR_TO_STATES: dict[str, list[str]] = {
    "Idle":                 ["idle"],
    "Idle Blinking":        ["idle_blink", "talk"],
    "Walking":              ["walk_right", "walk_left"],
    "Running":              ["run_right", "run_left"],
    "Hurt":                 ["hurt", "drag"],
    "Kicking":              ["kick", "happy"],
    "Dying":                ["dying"],
    "Falling Down":         ["falling"],
    "Jump Start":           ["jump_start"],
    "Jump Loop":            ["jump_loop"],
    "Sliding":              ["sliding"],
    "Throwing":             ["throwing"],
    "Throwing in The Air":  ["throwing_air"],
    "Run Throwing":         ["run_throwing"],
    "Shooting":             ["shooting"],
    "Shooting in The Air":  ["shooting_air"],
    "Run Shooting":         ["run_shooting"],
    "Slashing":             ["slashing"],
    "Slashing in The Air":  ["slashing_air"],
    "Run Slashing":         ["run_slashing"],
}

# States that should be horizontally flipped (auto-added when their dir exists)
AUTO_FLIP = {"walk_left", "run_left"}


# ── auto-detection helpers ──────────────────────────────────────────────

def _build_state_map(sprite_dir: str) -> dict[str, str]:
    """Scan subdirectories and return {state_name: dir_name} via DIR_TO_STATES."""
    state_map: dict[str, str] = {}
    if not os.path.isdir(sprite_dir):
        return state_map
    subdirs = {
        d for d in os.listdir(sprite_dir)
        if os.path.isdir(os.path.join(sprite_dir, d))
    }
    for dir_name, states in DIR_TO_STATES.items():
        if dir_name in subdirs:
            for state in states:
                state_map[state] = dir_name
    return state_map


def _build_flip_states(state_map: dict[str, str]) -> list[str]:
    """Return flip_states list based on which auto-flip states are present."""
    return [s for s in sorted(AUTO_FLIP) if s in state_map]


# ── discovery ───────────────────────────────────────────────────────────

def _load_characters() -> dict[str, dict]:
    """Scan sprites/*/character.json and build the full CHARACTERS dict."""
    characters: dict[str, dict] = {}

    if not os.path.isdir(SPRITES_ROOT):
        log.warning("Sprites root not found: %s", SPRITES_ROOT)
        return characters

    for folder in sorted(os.listdir(SPRITES_ROOT)):
        json_path = os.path.join(SPRITES_ROOT, folder, "character.json")
        if not os.path.isfile(json_path):
            continue

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping %s: %s", json_path, exc)
            continue

        name = data.get("name", folder)
        rel_path = f"sprites/{folder}"
        char_type = data.get("type", "sequence_dirs")

        if char_type == "sequence_dirs" and "state_map" not in data:
            abs_sprite_dir = os.path.join(SPRITES_ROOT, folder)
            state_map = _build_state_map(abs_sprite_dir)
            flip_states = _build_flip_states(state_map)
        else:
            state_map = data.get("state_map", {})
            flip_states = data.get("flip_states", [])

        characters[name] = {
            "type": char_type,
            "path": rel_path,
            "sprite_size": data.get("sprite_size", 128),
            "fps": data.get("fps", 8),
            "state_map": state_map,
            "flip_states": flip_states,
        }

    return characters


CHARACTERS: dict[str, dict] = _load_characters()


# ── public API (unchanged) ─────────────────────────────────────────────

def get_character_names() -> list[str]:
    """Return list of available character names."""
    return list(CHARACTERS.keys())


def get_character(name: str) -> dict:
    """Return character config by name, defaulting to first available."""
    if name in CHARACTERS:
        return CHARACTERS[name]
    fallback = "placeholder" if "placeholder" in CHARACTERS else next(iter(CHARACTERS), None)
    if fallback:
        return CHARACTERS[fallback]
    return {"type": "flat", "path": "sprites/placeholder", "sprite_size": 128,
            "fps": 6, "state_map": {}, "flip_states": []}


def get_sprites_dir(name: str) -> str:
    """Return the absolute sprites directory for a character."""
    char = get_character(name)
    return os.path.join(BASE_DIR, char["path"])


def get_character_preview(name: str) -> str | None:
    """Return absolute path to the first idle frame for a character, or None."""
    char = get_character(name)
    sprite_dir = os.path.join(BASE_DIR, char["path"])

    if char["type"] == "flat":
        # flat layout: idle_0.png in the sprite dir
        candidate = os.path.join(sprite_dir, "idle_0.png")
        return candidate if os.path.isfile(candidate) else None

    # sequence_dirs: look inside the Idle subdirectory
    idle_dir_name = char.get("state_map", {}).get("idle", "Idle")
    idle_dir = os.path.join(sprite_dir, idle_dir_name)
    if not os.path.isdir(idle_dir):
        return None
    frames = sorted(f for f in os.listdir(idle_dir) if f.lower().endswith(".png"))
    return os.path.join(idle_dir, frames[0]) if frames else None


def reload_characters() -> None:
    """Re-scan sprite folders (useful after adding packs at runtime)."""
    global CHARACTERS
    CHARACTERS = _load_characters()
    log.info("Reloaded characters: %s", list(CHARACTERS.keys()))
