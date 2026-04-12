"""LLM-based intent classification for user input.

When keyword matching fails, this module asks the LLM to classify the
user's intent into one of: click, close, minimize, navigate, vision, chat.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional, Callable

from utils.i18n import get_intent_classify_prompt

log = logging.getLogger("intent_classifier")

# Valid interaction intents (ones that trigger screen interaction)
_INTERACTION_INTENTS = frozenset({"click", "close", "minimize", "navigate", "type"})
_ALL_VALID_INTENTS = frozenset({"click", "close", "minimize", "navigate", "type", "vision", "chat"})

# Fallback prompt in case the locale file doesn't have one
_FALLBACK_PROMPT = (
    'Classify the user\'s intent from the following message.\n\n'
    'Supported types:\n'
    '- "click": press/click/tap/open a UI element\n'
    '- "close": close/quit/exit a window or app\n'
    '- "minimize": minimize/hide a window\n'
    '- "navigate": find/go to/locate something on screen\n'
    '- "type": write/type text into a UI element (input field, search bar, etc.)\n'
    '- "vision": look at or describe the screen\n'
    '- "chat": general conversation or question\n\n'
    'User message: "{question}"\n\n'
    'Respond ONLY with JSON: {{"intent": "<type>", "confidence": <0_to_100>, '
    '"target": "<element description if interaction, else empty string>", '
    '"text": "<text to type if intent is type, else empty string>"}}'
)

_SYSTEM_PROMPT = (
    "You are an intent classifier. Your ONLY job is to classify user messages "
    "into predefined intent categories. Respond ONLY with valid JSON — "
    "no extra text, no markdown, no explanations."
)


@dataclass
class IntentResult:
    """Structured result from LLM intent classification."""
    intent: str          # click | close | minimize | navigate | type | vision | chat
    confidence: int      # 0-100
    target: str          # target description (for interaction intents)
    type_text: str = ""  # text to type (only when intent="type")

    @property
    def is_interaction(self) -> bool:
        """True if this intent maps to a screen interaction action."""
        return self.intent in _INTERACTION_INTENTS


def classify_intent(text: str, llm, callback: Callable[[Optional[IntentResult]], None]):
    """Ask the LLM to classify user intent in a background thread.

    Parameters
    ----------
    text : str
        The raw user message.
    llm : OllamaProvider | OpenRouterProvider | GroqProvider
        Any LLM provider that implements ``generate(context, callback)``.
    callback : callable
        Called with an ``IntentResult`` on success or ``None`` on failure.
        Called from the LLM thread — the caller is responsible for
        marshalling to the GUI thread (e.g. via pyqtSignal).
    """
    prompt_template = get_intent_classify_prompt() or _FALLBACK_PROMPT
    user_prompt = prompt_template.replace("{question}", text)

    def _on_llm_response(raw_text: Optional[str]):
        if not raw_text:
            log.warning("Intent classify: LLM returned empty response")
            callback(None)
            return

        result = parse_intent_response(raw_text)
        if result is None:
            log.warning("Intent classify: could not parse response: %r", raw_text[:200])
        else:
            log.info("Intent classify: intent=%s conf=%d target=%r",
                     result.intent, result.confidence, result.target[:60])
        callback(result)

    llm.generate(
        _build_classify_context(user_prompt),
        _on_llm_response,
    )


def _build_classify_context(user_prompt: str) -> str:
    """Build the full context string for the intent classification call.

    We override the system prompt via the context itself since
    ``generate()`` uses the pet's system prompt by default.
    We prepend a directive to make the LLM behave as a classifier.
    """
    return f"[SYSTEM OVERRIDE] {_SYSTEM_PROMPT}\n\n{user_prompt}"


def parse_intent_response(raw_text: str) -> Optional[IntentResult]:
    """Parse the LLM's JSON response into an IntentResult.

    Tolerates markdown fences, think tags, and extra text around the JSON.
    Returns ``None`` if parsing fails or fields are invalid.
    """
    parsed = _parse_json(raw_text)
    if parsed is None:
        return None

    # Extract and validate fields
    intent = str(parsed.get("intent", "")).lower().strip()
    if intent not in _ALL_VALID_INTENTS:
        log.warning("Intent classify: unknown intent %r", intent)
        return None

    try:
        confidence = int(parsed.get("confidence", 0))
    except (ValueError, TypeError):
        confidence = 0
    confidence = max(0, min(100, confidence))

    target = str(parsed.get("target", "")).strip()
    type_text = str(parsed.get("text", "")).strip()

    return IntentResult(intent=intent, confidence=confidence, target=target, type_text=type_text)


def _parse_json(raw_text: str) -> Optional[dict]:
    """Extract JSON from LLM response, tolerating markdown fences, think tags, extra text.

    Same strategy as ScreenInteractionHandler._parse_llm_json:
    1. ``json.loads(stripped text)``
    2. Regex: content inside triple-backtick json fences
    3. Regex: first ``{...}`` block in the text
    """
    # Strip think tags first
    text = re.sub(r"<think>[\s\S]*?</think>", "", raw_text).strip()

    # 1. Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Try markdown json fence
    fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", text)
    if fence_match:
        try:
            result = json.loads(fence_match.group(1).strip())
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. Try first {...} block
    brace_match = re.search(r"\{[^{}]*\}", text)
    if brace_match:
        try:
            result = json.loads(brace_match.group(0))
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    return None
