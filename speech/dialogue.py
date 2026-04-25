import random
from typing import Optional

from utils.i18n import get_dialogues, get_app_groups


def _build_app_comments() -> dict:
    """Build flat keyword → comments lookup from current locale's app_groups.

    Sorted by keyword length descending so specific matches
    (e.g. "untitled - notepad") take priority over generic ones ("notepad").
    """
    comments = {}
    for _group in get_app_groups().values():
        for _kw in _group.get("keywords", []):
            comments[_kw] = _group.get("comments", [])
    return dict(sorted(comments.items(), key=lambda x: len(x[0]), reverse=True))


def get_line(trigger: str, pet_name: str = "Jacky", **kwargs) -> Optional[str]:
    """Get a random dialogue line for the given trigger."""
    pool = get_dialogues().get(trigger)
    if not pool:
        return None
    line = random.choice(pool)
    return line.format(name=pet_name, **kwargs)


def get_app_comment(app_hint: str, pet_name: str = "Jacky", process_name: str = "") -> Optional[str]:
    """Get a comment about a specific app.

    Checks both the window title and process name against APP_COMMENTS keys
    using a flexible 'contains' match.
    """
    app_comments = _build_app_comments()
    title_lower = app_hint.lower()
    proc_lower = process_name.lower()
    for key, lines in app_comments.items():
        if key in title_lower or key in proc_lower:
            line = random.choice(lines)
            return line.format(name=pet_name)
    # Fallback to generic
    return get_line("window_generic", pet_name)
