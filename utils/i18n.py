"""Internationalization (i18n) module for Jacky desktop pet.

Loads locale JSON files from the ``locales/`` directory and exposes
helpers to retrieve translated strings at runtime.
"""

import json
import logging
import os
from typing import Optional

log = logging.getLogger("i18n")

_current_lang: str = "es"
_strings: dict = {}
_locales_dir: str = ""


def _resolve_locales_dir() -> str:
    """Return the absolute path to the ``locales/`` directory."""
    # Works both in dev (running from repo root) and when frozen with PyInstaller
    import sys
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "locales")


def load_language(code: str) -> None:
    """Load a language file by its ISO code (e.g. ``'es'``, ``'en'``).

    Falls back to ``'es'`` if the requested file does not exist.
    """
    global _current_lang, _strings, _locales_dir
    _locales_dir = _resolve_locales_dir()
    path = os.path.join(_locales_dir, f"{code}.json")
    if not os.path.isfile(path):
        log.warning("Locale file not found: %s — falling back to 'es'", path)
        code = "es"
        path = os.path.join(_locales_dir, f"{code}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            _strings = json.load(f)
        _current_lang = code
        log.info("Loaded language '%s' from %s", code, path)
    except Exception as e:
        log.error("Failed to load locale '%s': %s", code, e)


def current_language() -> str:
    """Return the currently loaded language code."""
    return _current_lang


def t(key: str, **kwargs) -> str:
    """Translate a UI string by dot-separated key.

    Example::

        t("ui.menu_feed")          -> "🍔 Alimentar"
        t("ui.menu_pet", name="X") -> "🤗 Acariciar a X"

    Returns the key itself if the lookup fails (makes missing keys visible).
    """
    parts = key.split(".")
    node = _strings
    for part in parts:
        if isinstance(node, dict):
            node = node.get(part)
        else:
            node = None
            break
    if node is None:
        log.warning("Missing i18n key: '%s' (lang=%s)", key, _current_lang)
        return key
    if isinstance(node, str) and kwargs:
        try:
            return node.format(**kwargs)
        except KeyError:
            return node
    if isinstance(node, str):
        return node
    # If it's not a string (e.g. a list or dict), return str representation
    return str(node)


def get_dialogues() -> dict:
    """Return the ``dialogues`` dict for the current language.

    Each key maps to a list of format-string lines.
    """
    return _strings.get("dialogues", {})


def get_app_groups() -> dict:
    """Return the ``app_groups`` dict for the current language.

    Each group has ``keywords`` (list[str]) and ``comments`` (list[str]).
    """
    return _strings.get("app_groups", {})


def get_permission_defs() -> dict:
    """Return the ``permissions`` dict for the current language.

    Each key maps to ``{"label": ..., "desc": ...}``.
    """
    return _strings.get("permissions", {})


def get_vision_keywords() -> set:
    """Return the set of vision-trigger keywords for the current language."""
    kw = _strings.get("vision_keywords", [])
    return set(kw)


def get_interact_keywords() -> dict:
    """Return the screen-interaction keywords for the current language.

    Returns a dict like ``{"navigate": ["encuentra", ...], "click": [...], ...}``.
    """
    return _strings.get("interact_keywords", {})


def get_interact_prefixes() -> list[str]:
    """Return the screen-interaction prefixes (articles, prepositions) to strip.

    Returns a list of strings like ["a", "la", "el", "en", "sobre"].
    """
    return _strings.get("interact_prefixes", [])


def get_type_separators() -> list[str]:
    """Return separator words used to split text-to-type from the target element.

    Returns a list sorted by length (longest first) like
    ``["dentro de", "en el", "en la", "en"]``.
    """
    seps = _strings.get("type_separators", [])
    return sorted(seps, key=len, reverse=True)


def get_interact_system_prompt() -> str:
    """Return the dedicated technical system prompt for screen interaction tasks."""
    prompt = _strings.get("interact_system_prompt", "")
    if not prompt:
        return "You are a computer vision assistant. Your task is to locate elements in screenshots. Respond ONLY with valid JSON."
    return prompt


def get_interact_grid_prompt() -> str:
    """Return the grid-phase prompt template (contains {target}, {cols}, {rows}, {total})."""
    return _strings.get("interact_grid_prompt", "")


def get_interact_locate_prompt() -> str:
    """Return the locate prompt template for screen interaction (contains {target})."""
    return _strings.get("interact_locate_prompt", "")


def get_intent_classify_prompt() -> str:
    """Return the intent classification prompt template (contains {question})."""
    return _strings.get("intent_classify_prompt", "")


def get_interact_refine_prompt() -> str:
    """Return the refine prompt template for screen interaction (contains {target})."""
    return _strings.get("interact_refine_prompt", "")


def get_system_prompt(pet_name: str = "Jacky") -> str:
    """Return the LLM system prompt with ``{name}`` filled in."""
    template = _strings.get("llm_system_prompt", "")
    if not template:
        log.warning("No llm_system_prompt in locale '%s'", _current_lang)
        return f"You are {pet_name}, a virtual desktop pet. Be brief and fun."
    try:
        return template.format(name=pet_name)
    except KeyError:
        return template


def available_languages() -> list[tuple[str, str]]:
    """Discover available languages from locale files.

    Returns a sorted list of ``(code, display_name)`` tuples, e.g.
    ``[("en", "English"), ("es", "Español")]``.
    """
    locales_dir = _resolve_locales_dir()
    langs: list[tuple[str, str]] = []
    if not os.path.isdir(locales_dir):
        return [("es", "Español")]
    for fname in os.listdir(locales_dir):
        if not fname.endswith(".json"):
            continue
        code = fname[:-5]
        try:
            with open(os.path.join(locales_dir, fname), "r", encoding="utf-8") as f:
                data = json.load(f)
            name = data.get("meta", {}).get("name", code)
            langs.append((code, name))
        except Exception:
            langs.append((code, code))
    langs.sort(key=lambda x: x[0])
    return langs
