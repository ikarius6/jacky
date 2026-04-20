"""Routine file discovery and loading.

Scans a ``routines/`` directory for ``.json`` files and returns
validated ``RoutineDefinition`` instances.
"""

import json
import logging
import os
from typing import List

from core.routines.models import RoutineDefinition

log = logging.getLogger("routines.loader")


def _resolve_routines_dir() -> str:
    """Return the absolute path to the ``routines/`` directory."""
    import sys
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "routines")


def load_routines(routines_dir: str | None = None) -> List[RoutineDefinition]:
    """Discover and load all routine JSON files from *routines_dir*.

    Invalid files are logged and skipped.  Returns only enabled routines.
    """
    if routines_dir is None:
        routines_dir = _resolve_routines_dir()

    if not os.path.isdir(routines_dir):
        log.debug("Routines directory not found: %s", routines_dir)
        return []

    routines: List[RoutineDefinition] = []
    for fname in sorted(os.listdir(routines_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(routines_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Failed to load routine file '%s': %s", fpath, exc)
            continue

        if not isinstance(data, dict):
            log.warning("Routine file '%s' is not a JSON object", fpath)
            continue

        routine = RoutineDefinition.from_dict(data, source_file=fpath)
        if routine is None:
            continue
        if not routine.enabled:
            log.debug("Routine '%s' is disabled, skipping", routine.id)
            continue

        # Check for duplicate IDs
        if any(r.id == routine.id for r in routines):
            log.warning("Duplicate routine id '%s' in '%s', skipping", routine.id, fpath)
            continue

        routines.append(routine)
        log.info("ROUTINE_LOADED id=%s title=%r auto=%s file=%s",
                 routine.id, routine.title, routine.is_automatic, fname)

    log.info("Loaded %d routine(s) from %s", len(routines), routines_dir)
    return routines
