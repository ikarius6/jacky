"""Screen interaction package – split from the original monolithic module.

Re-exports the public API so that ``from core.screen_interaction import …``
continues to work unchanged.
"""

from core.screen_interaction.task import ScreenInteractionTask       # noqa: F401
from core.screen_interaction.handler import ScreenInteractionHandler # noqa: F401
