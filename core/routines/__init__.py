"""Routines workflow engine for Jacky desktop pet.

Allows the pet to fetch data from APIs, parse responses, evaluate
conditional logic, and deliver results via speech / notification / log.
"""

from core.routines.models import RoutineDefinition, RoutineStep, RoutineAction
from core.routines.manager import RoutineManager

__all__ = ["RoutineDefinition", "RoutineStep", "RoutineAction", "RoutineManager"]
