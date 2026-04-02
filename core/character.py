"""
Character definitions — maps sprite packs to pet animation states.

Each character entry defines:
  - type: "flat" (single dir, {state}_{idx}.png) or "sequence_dirs" (subdirectories per animation)
  - path: relative path from project root to the sprites directory
  - state_map: maps internal animation names -> directory/prefix names
  - flip_states: animation names that should be horizontally flipped
  - sprite_size: suggested sprite size (can be overridden in config)
  - fps: suggested FPS for this character
"""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHARACTERS = {
    "placeholder": {
        "type": "flat",
        "path": "sprites/placeholder",
        "sprite_size": 128,
        "fps": 6,
        "state_map": {},  # flat type uses filename prefixes directly
        "flip_states": [],
    },
    "Forest Ranger 1": {
        "type": "sequence_dirs",
        "path": "sprites/Forest_Ranger_1",
        "sprite_size": 128,
        "fps": 10,
        "state_map": {
            # Core states
            "idle": "Idle",
            "idle_blink": "Idle Blinking",
            "walk_right": "Walking",
            "walk_left": "Walking",
            "talk": "Idle Blinking",
            "drag": "Hurt",
            "happy": "Kicking",
            # Extra states
            "hurt": "Hurt",
            "dying": "Dying",
            "falling": "Falling Down",
            "jump_start": "Jump Start",
            "jump_loop": "Jump Loop",
            "kick": "Kicking",
            "run_right": "Running",
            "run_left": "Running",
            "shooting": "Shooting",
            "shooting_air": "Shooting in The Air",
            "sliding": "Sliding",
            "throwing": "Throwing",
            "throwing_air": "Throwing in The Air",
            "run_shooting": "Run Shooting",
            "run_throwing": "Run Throwing",
        },
        "flip_states": ["walk_left", "run_left"],
    },
    "Forest Ranger 2": {
        "type": "sequence_dirs",
        "path": "sprites/Forest_Ranger_2",
        "sprite_size": 128,
        "fps": 10,
        "state_map": {
            # Core states
            "idle": "Idle",
            "idle_blink": "Idle Blinking",
            "walk_right": "Walking",
            "walk_left": "Walking",
            "talk": "Idle Blinking",
            "drag": "Hurt",
            "happy": "Kicking",
            # Extra states
            "hurt": "Hurt",
            "dying": "Dying",
            "falling": "Falling Down",
            "jump_start": "Jump Start",
            "jump_loop": "Jump Loop",
            "kick": "Kicking",
            "run_right": "Running",
            "run_left": "Running",
            "shooting": "Shooting",
            "shooting_air": "Shooting in The Air",
            "sliding": "Sliding",
            "throwing": "Throwing",
            "throwing_air": "Throwing in The Air",
            "run_shooting": "Run Shooting",
            "run_throwing": "Run Throwing",
        },
        "flip_states": ["walk_left", "run_left"],
    },
    "Forest Ranger 3": {
        "type": "sequence_dirs",
        "path": "sprites/Forest_Ranger_3",
        "sprite_size": 128,
        "fps": 10,
        "state_map": {
            # Core states
            "idle": "Idle",
            "idle_blink": "Idle Blinking",
            "walk_right": "Walking",
            "walk_left": "Walking",
            "talk": "Idle Blinking",
            "drag": "Hurt",
            "happy": "Kicking",
            # Extra states
            "hurt": "Hurt",
            "dying": "Dying",
            "falling": "Falling Down",
            "jump_start": "Jump Start",
            "jump_loop": "Jump Loop",
            "kick": "Kicking",
            "run_right": "Running",
            "run_left": "Running",
            "slashing": "Slashing",
            "slashing_air": "Slashing in The Air",
            "sliding": "Sliding",
            "throwing": "Throwing",
            "throwing_air": "Throwing in The Air",
            "run_slashing": "Run Slashing",
            "run_throwing": "Run Throwing",
        },
        "flip_states": ["walk_left", "run_left"],
    },
    "Skeleton Warrior 1": {
        "type": "sequence_dirs",
        "path": "sprites/Skeleton_Warrior_1",
        "sprite_size": 128,
        "fps": 10,
        "state_map": {
            # Core states
            "idle": "Idle",
            "idle_blink": "Idle Blinking",
            "walk_right": "Walking",
            "walk_left": "Walking",
            "talk": "Idle Blinking",
            "drag": "Hurt",
            "happy": "Kicking",
            # Extra states
            "hurt": "Hurt",
            "dying": "Dying",
            "falling": "Falling Down",
            "jump_start": "Jump Start",
            "jump_loop": "Jump Loop",
            "kick": "Kicking",
            "run_right": "Running",
            "run_left": "Running",
            "slashing": "Slashing",
            "slashing_air": "Slashing in The Air",
            "sliding": "Sliding",
            "throwing": "Throwing",
            "throwing_air": "Throwing in The Air",
            "run_slashing": "Run Slashing",
            "run_throwing": "Run Throwing",
        },
        "flip_states": ["walk_left", "run_left"],
    },
    "Skeleton Warrior 2": {
        "type": "sequence_dirs",
        "path": "sprites/Skeleton_Warrior_2",
        "sprite_size": 128,
        "fps": 10,
        "state_map": {
            # Core states
            "idle": "Idle",
            "idle_blink": "Idle Blinking",
            "walk_right": "Walking",
            "walk_left": "Walking",
            "talk": "Idle Blinking",
            "drag": "Hurt",
            "happy": "Kicking",
            # Extra states
            "hurt": "Hurt",
            "dying": "Dying",
            "falling": "Falling Down",
            "jump_start": "Jump Start",
            "jump_loop": "Jump Loop",
            "kick": "Kicking",
            "run_right": "Running",
            "run_left": "Running",
            "slashing": "Slashing",
            "slashing_air": "Slashing in The Air",
            "sliding": "Sliding",
            "throwing": "Throwing",
            "throwing_air": "Throwing in The Air",
            "run_slashing": "Run Slashing",
            "run_throwing": "Run Throwing",
        },
        "flip_states": ["walk_left", "run_left"],
    },
    "Skeleton Warrior 3": {
        "type": "sequence_dirs",
        "path": "sprites/Skeleton_Warrior_3",
        "sprite_size": 128,
        "fps": 10,
        "state_map": {
            # Core states
            "idle": "Idle",
            "idle_blink": "Idle Blinking",
            "walk_right": "Walking",
            "walk_left": "Walking",
            "talk": "Idle Blinking",
            "drag": "Hurt",
            "happy": "Kicking",
            # Extra states
            "hurt": "Hurt",
            "dying": "Dying",
            "falling": "Falling Down",
            "jump_start": "Jump Start",
            "jump_loop": "Jump Loop",
            "kick": "Kicking",
            "run_right": "Running",
            "run_left": "Running",
            "slashing": "Slashing",
            "slashing_air": "Slashing in The Air",
            "sliding": "Sliding",
            "throwing": "Throwing",
            "throwing_air": "Throwing in The Air",
            "run_slashing": "Run Slashing",
            "run_throwing": "Run Throwing",
        },
        "flip_states": ["walk_left", "run_left"],
    },
}


def get_character_names():
    """Return list of available character names."""
    return list(CHARACTERS.keys())


def get_character(name: str) -> dict:
    """Return character config by name, defaulting to placeholder."""
    return CHARACTERS.get(name, CHARACTERS["placeholder"])


def get_sprites_dir(name: str) -> str:
    """Return the absolute sprites directory for a character."""
    char = get_character(name)
    return os.path.join(BASE_DIR, char["path"])
