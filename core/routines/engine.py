"""Workflow execution engine for the routines system.

Runs a single routine: executes steps sequentially, interpolates
variables, evaluates logic, and returns the resolved action + context.
All HTTP work happens off the Qt main thread.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

import requests

from core.routines.models import RoutineDefinition, RoutineStep, RoutineAction
from core.routines.parsers import parse_value
from core.routines.logic import resolve_action

log = logging.getLogger("routines.engine")

_VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")


@dataclass
class RoutineResult:
    """Result of running a routine."""
    routine_id: str
    success: bool
    action: Optional[RoutineAction] = None
    context: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


def interpolate(text: str, context: Dict[str, Any]) -> str:
    """Replace ``{{var}}`` placeholders with values from *context*."""
    def _repl(m):
        key = m.group(1)
        val = context.get(key, "")
        return str(val)
    return _VAR_PATTERN.sub(_repl, text)


def interpolate_dict(d: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-interpolate all string values in a dict."""
    result: Dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = interpolate(v, context)
        elif isinstance(v, dict):
            result[k] = interpolate_dict(v, context)
        elif isinstance(v, list):
            result[k] = [
                interpolate(item, context) if isinstance(item, str) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


def _execute_request(step: RoutineStep, context: Dict[str, Any]) -> str:
    """Execute an HTTP request step and return the response body text."""
    url = interpolate(step.url, context)
    headers = interpolate_dict(step.headers, context) if step.headers else {}
    params = interpolate_dict(step.params, context) if step.params else {}
    body = interpolate_dict(step.body, context) if step.body else None

    log.info("REQUEST %s %s (timeout=%ds)", step.method, url, step.timeout)

    resp = requests.request(
        method=step.method,
        url=url,
        headers=headers,
        params=params,
        json=body,
        timeout=step.timeout,
    )
    resp.raise_for_status()
    return resp.text


def _execute_parse(step: RoutineStep, context: Dict[str, Any]) -> str:
    """Execute a parse step and return the extracted value."""
    raw_input = interpolate(step.input, context)
    return parse_value(raw_input, step.parser, step.query)


def _execute_filesystem(step: RoutineStep, context: Dict[str, Any]) -> str:
    """Execute a filesystem step and return a JSON result."""
    query = step.query
    if query == "list_desktop":
        from utils.desktop_organizer import list_desktop_files
        entries = list_desktop_files()
        return json.dumps(entries, ensure_ascii=False)
    else:
        log.warning("Unknown filesystem query '%s'", query)
        return "[]"


def run_routine(routine: RoutineDefinition) -> RoutineResult:
    """Execute a routine synchronously.  Call from a worker thread.

    Returns a ``RoutineResult`` with the resolved action and context.
    """
    rid = routine.id
    log.info("ROUTINE_START id=%s title=%r", rid, routine.title)

    # Initialize context with predefined variables
    context: Dict[str, Any] = dict(routine.variables)
    context["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    context["routine_id"] = rid
    context["routine_title"] = routine.title

    # Execute steps sequentially
    for step in routine.steps:
        log.debug("STEP id=%s type=%s", step.id, step.type)
        try:
            if step.type == "request":
                result = _execute_request(step, context)
            elif step.type == "parse":
                result = _execute_parse(step, context)
            elif step.type == "filesystem":
                result = _execute_filesystem(step, context)
            else:
                log.warning("Unknown step type '%s' in routine '%s'", step.type, rid)
                continue

            if step.output_var:
                context[step.output_var] = result
                log.debug("STEP %s -> %s = %r", step.id, step.output_var,
                          str(result)[:120])

        except Exception as exc:
            error_msg = f"Step '{step.id}' failed: {exc}"
            log.error("ROUTINE_STEP_FAIL id=%s step=%s: %s", rid, step.id, exc)
            return RoutineResult(
                routine_id=rid, success=False, context=context, error=error_msg,
            )

    # Evaluate logic block to determine action
    action_name: Optional[str] = None
    if routine.logic:
        action_name = resolve_action(routine.logic, context)
        log.debug("LOGIC resolved action: %s", action_name)

    # Fallback: use "default" action only (do NOT pick the first arbitrary action)
    if action_name is None:
        if "default" in routine.actions:
            action_name = "default"

    action: Optional[RoutineAction] = None
    if action_name and action_name in routine.actions:
        action = routine.actions[action_name]
        
        from utils.i18n import current_language
        lang = current_language()
        
        def _get_localized(val: Any) -> str:
            if isinstance(val, dict):
                if lang in val:
                    return str(val[lang])
                if "en" in val:
                    return str(val["en"])
                if val:
                    return str(next(iter(val.values())))
                return ""
            return str(val or "")
            
        action = RoutineAction(
            name=action.name, type=action.type,
            llm=interpolate(_get_localized(action.llm), context),
            nollm=interpolate(_get_localized(action.nollm), context),
            message=interpolate(_get_localized(action.message), context),
            confirm_msg=interpolate(_get_localized(action.confirm_msg), context),
        )
    elif action_name:
        log.warning("Action '%s' not found in routine '%s'", action_name, rid)

    log.info("ROUTINE_DONE id=%s action=%s", rid, action_name or "(none)")
    return RoutineResult(
        routine_id=rid, success=True, action=action, context=context,
    )
