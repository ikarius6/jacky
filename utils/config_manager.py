import json
import os

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
}

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        merged = {**DEFAULT_CONFIG, **user_cfg}
        return merged
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
