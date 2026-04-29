"""
Character auto-discovery — scans sprites/*/character.json to register characters.

Each sprite pack needs a small ``character.json`` next to its frames::

    {
        "name": "Forest Ranger 1",
        "sprite_size": 128,
        "fps": 10,
        "sprite_facing": "right"
    }

Optional ``sprite_facing`` (``"right"`` or ``"left"``, default ``"right"``) tells
the engine which direction the raw sprite frames face.  When the pet needs to
face the opposite direction the frames are horizontally flipped.

For ``sequence_dirs`` packs the state_map is **auto-detected** from the
subdirectory names using DIR_TO_STATES.  You can still supply an explicit
``state_map`` / ``type`` in the JSON to override.

For ``flat`` packs (like placeholder) set ``"type": "flat"`` in the JSON.
"""

import json
import logging
import os

from utils.paths import get_data_dir, get_writable_sprites_dir

log = logging.getLogger(__name__)

BASE_DIR = get_data_dir()
SPRITES_ROOT = os.path.join(BASE_DIR, "sprites")
WRITABLE_SPRITES_ROOT = get_writable_sprites_dir()

# ── standard directory-name → internal-state(s) mapping ────────────────
# Each entry maps a sprite subdirectory name to one or more internal states.
DIR_TO_STATES: dict[str, list[str]] = {
    # ── existing sprite directories ──
    "Idle":                 ["idle"],
    "Idle2":                ["idle2"],
    "Idle Blinking":        ["idle_blink"],
    "Talk":                 ["talk"],
    "Walking":              ["walk"],
    "Running":              ["run"],
    "Hurt":                 ["hurt"],
    "Drag":                 ["drag"],
    "Kicking":              ["kick"],
    "Happy":                ["happy"],
    "Happy2":               ["happy2"],
    "Dying":                ["dying"],
    "Falling Down":         ["falling"],
    "Jump Loop":            ["jump_loop"],
    "Shooting":             ["shooting"],
    "Slashing":             ["slashing"],
    # ── new animation directories (ready for future sprite packs) ──
    "Eating":               ["eating"],
    "Dance":                ["dance"],
    "Getting Pet":          ["getting_pet"],
    "Getting Pet2":         ["getting_pet2"],
    "Getting Pet3":         ["getting_pet3"],
    "Peeking":              ["peeking"],
    "Sleeping":             ["sleeping"],
    "Taking Notes":         ["taking_notes"],
    "Error":                ["error"],
    "Taking Picture":       ["taking_picture"],
    "Rocking":              ["rocking"],
    "Confused":             ["confused"],
    "Dizzy":                ["dizzy"],
    "Thinking":             ["thinking"],
    "Loading":              ["loading"],
    "Typing":               ["typing"],
    "Typing2":              ["typing2"],
    "Alerting":             ["alerting"],
}

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


# ── discovery ───────────────────────────────────────────────────────────

def _scan_sprites_dir(root: str, source: str) -> dict[str, dict]:
    """Scan a single sprites root for character.json files.

    *source* is ``"bundled"`` or ``"downloaded"`` and is stored on each entry.
    """
    characters: dict[str, dict] = {}
    if not os.path.isdir(root):
        return characters

    for folder in sorted(os.listdir(root)):
        json_path = os.path.join(root, folder, "character.json")
        if not os.path.isfile(json_path):
            continue

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping %s: %s", json_path, exc)
            continue

        name = data.get("name", folder)
        abs_sprite_dir = os.path.join(root, folder)
        char_type = data.get("type", "sequence_dirs")

        if char_type == "sequence_dirs" and "state_map" not in data:
            state_map = _build_state_map(abs_sprite_dir)
        else:
            state_map = data.get("state_map", {})

        sprite_facing = data.get("sprite_facing", "right").lower()
        if sprite_facing not in ("right", "left"):
            log.warning("%s: invalid sprite_facing %r, defaulting to 'right'", json_path, sprite_facing)
            sprite_facing = "right"

        characters[name] = {
            "type": char_type,
            "path": abs_sprite_dir,
            "sprite_size": data.get("sprite_size", 128),
            "fps": data.get("fps", 8),
            "state_map": state_map,
            "sprite_facing": sprite_facing,
            "version": data.get("version"),
            "source": source,
            "folder_id": folder,
        }

    return characters


def _load_characters() -> dict[str, dict]:
    """Scan bundled + writable sprites dirs and build the CHARACTERS dict.

    Downloaded characters (writable) override bundled ones if names collide.
    """
    # 1. Bundled (read-only in frozen mode)
    characters = _scan_sprites_dir(SPRITES_ROOT, "bundled")

    # 2. Downloaded / writable (next to .exe in frozen mode)
    if os.path.normpath(WRITABLE_SPRITES_ROOT) != os.path.normpath(SPRITES_ROOT):
        downloaded = _scan_sprites_dir(WRITABLE_SPRITES_ROOT, "downloaded")
        characters.update(downloaded)  # downloaded wins on name collision

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
    fallback = "Forest_Ranger_3" if "Forest_Ranger_3" in CHARACTERS else next(iter(CHARACTERS), None)
    if fallback:
        return CHARACTERS[fallback]
    return {"type": "flat", "path": os.path.join(SPRITES_ROOT, "Forest_Ranger_3"),
            "sprite_size": 128, "fps": 6, "state_map": {}, "sprite_facing": "right"}


def get_sprites_dir(name: str) -> str:
    """Return the absolute sprites directory for a character."""
    char = get_character(name)
    return char["path"]


def get_writable_sprites_root() -> str:
    """Return the writable sprites root where downloaded packs live."""
    return WRITABLE_SPRITES_ROOT


def get_character_preview(name: str) -> str | None:
    """Return absolute path to the first idle frame for a character, or None."""
    char = get_character(name)
    sprite_dir = char["path"]

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
