"""Conditional logic evaluator for the routines workflow engine.

Evaluates nested AND/OR conditions and resolves which action to execute.
"""

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("routines.logic")

_OPERATORS = {
    ">":        lambda a, b: a > b,
    "<":        lambda a, b: a < b,
    ">=":       lambda a, b: a >= b,
    "<=":       lambda a, b: a <= b,
    "==":       lambda a, b: a == b,
    "!=":       lambda a, b: a != b,
    "contains": lambda a, b: str(b) in str(a),
}


def _coerce_numeric(value: Any) -> Any:
    """Try to convert a value to float for numeric comparisons."""
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except (ValueError, TypeError):
            pass
    return value


def evaluate_condition(condition: dict, context: dict) -> bool:
    """Evaluate a condition node recursively.

    Supports::

        {"and": [<conditions...>]}
        {"or":  [<conditions...>]}
        {"var": "name", "op": ">", "val": 10}
    """
    if "and" in condition:
        children = condition["and"]
        if not isinstance(children, list):
            log.warning("'and' value must be a list")
            return False
        return all(evaluate_condition(c, context) for c in children)

    if "or" in condition:
        children = condition["or"]
        if not isinstance(children, list):
            log.warning("'or' value must be a list")
            return False
        return any(evaluate_condition(c, context) for c in children)

    # Leaf condition: {var, op, val}
    var_name = condition.get("var")
    op = condition.get("op")
    target = condition.get("val")

    if var_name is None or op is None:
        log.warning("Condition missing 'var' or 'op': %s", condition)
        return False

    if op not in _OPERATORS:
        log.warning("Unknown operator '%s'", op)
        return False

    raw_val = context.get(var_name)
    if raw_val is None:
        log.debug("Variable '%s' not in context, treating as False", var_name)
        return False

    # Numeric coercion for comparison operators
    if op in (">", "<", ">=", "<="):
        raw_val = _coerce_numeric(raw_val)
        target = _coerce_numeric(target)

    try:
        return _OPERATORS[op](raw_val, target)
    except (TypeError, ValueError) as exc:
        log.warning("Condition eval error (%s %s %s): %s", var_name, op, target, exc)
        return False


def resolve_action(logic_block: List[dict], context: dict) -> Optional[str]:
    """Walk the logic block and return the name of the action to execute.

    Each entry in *logic_block* has the form::

        {"if": <condition>, "then": "action_name", "else": "action_name"}

    Evaluates entries in order.  Returns the first matching ``then`` or
    ``else`` action name.  Returns ``None`` if no logic applies.
    """
    for entry in logic_block:
        if not isinstance(entry, dict):
            continue
        cond = entry.get("if")
        if cond is None:
            continue
        if evaluate_condition(cond, context):
            action_name = entry.get("then")
        else:
            action_name = entry.get("else")
        if action_name:
            return str(action_name)
    return None
