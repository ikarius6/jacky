import json
import logging
import os

from utils.paths import get_config_dir

log = logging.getLogger("config_manager")

DEFAULT_CONFIG = {
    "pet_name": "Jacky",
    "sprite_set": "placeholder",
    "character": "placeholder",
    "sprite_size": 128,
    "movement_speed": 3,
    "idle_interval": [5, 15],
    "chat_interval": [20, 60],
    "window_check_interval": [10, 30],
    "llm_enabled": False,
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3",
    "window_interaction_enabled": True,
    "window_push_enabled": True,
    "always_on_top": True,
    "bubble_timeout": 5,
    "silent_mode": False,
    "peer_interaction_enabled": True,
    "max_peer_instances": 5,
    "peer_check_interval": [8, 20],
    "groq_api_keys": [],
    "groq_model": "meta-llama/llama-4-scout-17b-16e-instruct",
}

# Schema: key -> (type, min, max, choices)
# - type: expected Python type
# - min/max: numeric bounds (None if not applicable)
# - choices: allowed values (None if not restricted)
_SCHEMA = {
    "pet_name":                   (str,   None, None, None),
    "sprite_set":                 (str,   None, None, None),
    "character":                  (str,   None, None, None),
    "sprite_size":                (int,   32,   512,  None),
    "movement_speed":             (int,   1,    10,   None),
    "llm_enabled":                (bool,  None, None, None),
    "ollama_url":                 (str,   None, None, None),
    "ollama_model":               (str,   None, None, None),
    "window_interaction_enabled": (bool,  None, None, None),
    "window_push_enabled":        (bool,  None, None, None),
    "always_on_top":              (bool,  None, None, None),
    "bubble_timeout":             (int,   1,    60,   None),
    "llm_provider":               (str,   None, None, ["ollama", "openrouter", "groq"]),
    "openrouter_api_key":         (str,   None, None, None),
    "openrouter_model":           (str,   None, None, None),
    "groq_model":                 (str,   None, None, None),
    "debug_logging":              (bool,  None, None, None),
    "silent_mode":                (bool,  None, None, None),
    "peer_interaction_enabled":   (bool,  None, None, None),
    "max_peer_instances":         (int,   1,    20,   None),
}

# Interval keys: list of exactly 2 positive ints where [0] <= [1]
_INTERVAL_KEYS = {"idle_interval", "chat_interval", "window_check_interval", "peer_check_interval"}

CONFIG_PATH = os.path.join(get_config_dir(), "config.json")


def _validate_interval(key: str, value, default):
    """Validate an interval value [min, max]. Returns corrected value or default."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        log.warning("Config '%s': expected [min, max] list, got %r — using default", key, value)
        return list(default)
    try:
        lo, hi = int(value[0]), int(value[1])
    except (TypeError, ValueError):
        log.warning("Config '%s': non-numeric values %r — using default", key, value)
        return list(default)
    if lo < 1:
        lo = 1
    if hi < lo:
        hi = lo
    if [lo, hi] != [value[0], value[1]]:
        log.warning("Config '%s': clamped %r → [%d, %d]", key, value, lo, hi)
    return [lo, hi]


def _validate(config: dict) -> dict:
    """Validate and sanitize config values. Invalid values are replaced with defaults."""
    for key, (expected_type, vmin, vmax, choices) in _SCHEMA.items():
        if key not in config:
            continue
        value = config[key]

        # Type check — attempt coercion for numeric types
        if not isinstance(value, expected_type):
            if expected_type in (int, float):
                try:
                    value = expected_type(value)
                    config[key] = value
                    log.warning("Config '%s': coerced to %s → %r", key, expected_type.__name__, value)
                except (TypeError, ValueError):
                    log.warning("Config '%s': expected %s, got %s — using default",
                                key, expected_type.__name__, type(value).__name__)
                    config[key] = DEFAULT_CONFIG[key]
                    continue
            elif expected_type is bool and isinstance(value, (int, float)):
                config[key] = bool(value)
                value = config[key]
            else:
                log.warning("Config '%s': expected %s, got %s — using default",
                            key, expected_type.__name__, type(value).__name__)
                config[key] = DEFAULT_CONFIG[key]
                continue

        # Range check
        if vmin is not None and value < vmin:
            log.warning("Config '%s': %r below minimum %r — clamped", key, value, vmin)
            config[key] = vmin
        elif vmax is not None and value > vmax:
            log.warning("Config '%s': %r above maximum %r — clamped", key, value, vmax)
            config[key] = vmax

        # Choices check
        if choices is not None and config[key] not in choices:
            log.warning("Config '%s': %r not in %r — using default", key, config[key], choices)
            config[key] = DEFAULT_CONFIG.get(key, choices[0])

    # Validate interval keys
    for key in _INTERVAL_KEYS:
        if key in config:
            config[key] = _validate_interval(key, config[key], DEFAULT_CONFIG[key])

    # Validate groq_api_keys: must be a list of non-empty strings
    if "groq_api_keys" in config:
        val = config["groq_api_keys"]
        if not isinstance(val, list):
            log.warning("Config 'groq_api_keys': expected list, got %s — using default", type(val).__name__)
            config["groq_api_keys"] = []
        else:
            config["groq_api_keys"] = [k for k in val if isinstance(k, str) and k.strip()]

    # Validate permissions dict if present
    if "permissions" in config:
        perms = config["permissions"]
        if not isinstance(perms, dict):
            log.warning("Config 'permissions': expected dict, got %s — using default", type(perms).__name__)
            config.pop("permissions")
        else:
            for pk, pv in list(perms.items()):
                if not isinstance(pv, bool):
                    log.warning("Config 'permissions.%s': expected bool, got %s — removed", pk, type(pv).__name__)
                    perms.pop(pk)

    return config


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
        except json.JSONDecodeError as e:
            log.warning("Config file has invalid JSON, using defaults: %s", e)
            return dict(DEFAULT_CONFIG)
        except OSError as e:
            log.warning("Could not read config file, using defaults: %s", e)
            return dict(DEFAULT_CONFIG)
        merged = {**DEFAULT_CONFIG, **user_cfg}
        return _validate(merged)
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
