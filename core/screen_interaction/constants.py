"""Shared constants for the screen-interaction feature."""

# Confidence threshold: skip refinement if above this
CONFIDENCE_THRESHOLD = 90

# Safety timeout for the whole task (seconds)
TASK_TIMEOUT_MS = 60_000

# Grid dimensions for coarse locate phase
GRID_COLS = 8
GRID_ROWS = 6

# Sub-grid dimensions for precise locate phase (phase 2)
SUB_COLS = 8
SUB_ROWS = 6

# Minimum LLM confidence to trust an intent classification result
INTENT_CONFIDENCE_THRESHOLD = 70
