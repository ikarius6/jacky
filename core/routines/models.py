"""Data models for the routines workflow engine."""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

log = logging.getLogger("routines.models")


@dataclass
class RoutineStep:
    """A single step in a routine workflow."""
    id: str
    type: str                                # "request" | "parse"
    # Request fields
    method: str = "GET"
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, str] = field(default_factory=dict)
    body: Optional[Dict[str, Any]] = None
    timeout: int = 10
    # Parse fields
    parser: str = ""                         # "json" | "xml" | "regex"
    query: str = ""
    input: str = ""                          # raw text or {{var}} reference
    # Common
    output_var: str = ""


@dataclass
class RoutineAction:
    """An action to execute at the end of a routine."""
    name: str
    type: str                                # "say" | "log" | "notification"
    llm: Union[str, Dict[str, str]] = ""       # prompt for LLM
    nollm: Union[str, Dict[str, str]] = ""     # fallback when LLM disabled
    message: Union[str, Dict[str, str]] = ""   # for log / notification


@dataclass
class RoutineSchedule:
    """Schedule configuration for automatic routines."""
    interval: int = 0                        # seconds, 0 = manual only


@dataclass
class RoutineDefinition:
    """Complete routine definition loaded from a JSON file."""
    id: str
    title: str
    description: str = ""
    schedule: Optional[RoutineSchedule] = None
    triggers: List[str] = field(default_factory=list)
    enabled: bool = True
    steps: List[RoutineStep] = field(default_factory=list)
    logic: List[Dict[str, Any]] = field(default_factory=list)
    actions: Dict[str, RoutineAction] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    source_file: str = ""                    # path to the .json file

    @property
    def is_automatic(self) -> bool:
        """True if this routine has a schedule interval > 0."""
        return self.schedule is not None and self.schedule.interval > 0

    @property
    def is_manual(self) -> bool:
        """True if this routine has no schedule (manual trigger only)."""
        return not self.is_automatic

    @classmethod
    def from_dict(cls, data: dict, source_file: str = "") -> Optional["RoutineDefinition"]:
        """Parse a routine definition from a raw dict.

        Returns None if required fields are missing or invalid.
        """
        rid = data.get("id")
        title = data.get("title")
        if not rid or not title:
            log.warning("Routine missing 'id' or 'title' in %s", source_file)
            return None

        # Schedule
        sched_raw = data.get("schedule")
        schedule = None
        if isinstance(sched_raw, dict) and sched_raw.get("interval"):
            try:
                schedule = RoutineSchedule(interval=int(sched_raw["interval"]))
            except (ValueError, TypeError):
                log.warning("Invalid schedule interval in routine '%s'", rid)

        # Steps
        steps: List[RoutineStep] = []
        for s in data.get("steps", []):
            if not isinstance(s, dict):
                continue
            sid = s.get("id", "")
            stype = s.get("type", "")
            if stype not in ("request", "parse"):
                log.warning("Unknown step type '%s' in routine '%s'", stype, rid)
                continue
            steps.append(RoutineStep(
                id=sid,
                type=stype,
                method=str(s.get("method", "GET")).upper(),
                url=str(s.get("url", "")),
                headers={str(k): str(v) for k, v in s.get("headers", {}).items()},
                params={str(k): str(v) for k, v in s.get("params", {}).items()},
                body=s.get("body") if isinstance(s.get("body"), dict) else None,
                timeout=int(s.get("timeout", 10)),
                parser=str(s.get("parser", "")),
                query=str(s.get("query", "")),
                input=str(s.get("input", "")),
                output_var=str(s.get("output_var", "")),
            ))

        # Actions
        actions: Dict[str, RoutineAction] = {}
        for aname, aval in data.get("actions", {}).items():
            if not isinstance(aval, dict):
                continue
            actions[aname] = RoutineAction(
                name=str(aname),
                type=str(aval.get("type", "say")),
                llm=aval.get("llm", ""),
                nollm=aval.get("nollm", ""),
                message=aval.get("message", ""),
            )

        # Logic
        logic = data.get("logic", [])
        if not isinstance(logic, list):
            logic = []

        return cls(
            id=str(rid),
            title=str(title),
            description=str(data.get("description", "")),
            schedule=schedule,
            triggers=[str(t) for t in data.get("triggers", []) if t],
            enabled=bool(data.get("enabled", True)),
            steps=steps,
            logic=logic,
            actions=actions,
            variables={str(k): v for k, v in data.get("variables", {}).items()},
            source_file=source_file,
        )
