import json
import re
import threading
from typing import Optional, Callable

import requests


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks produced by reasoning models (e.g. Qwen3)."""
    return re.sub(r"<think>[\s\S]*?</think>", "", text).strip()


SYSTEM_PROMPT = """Eres Jacky, una mascota virtual chibi que vive en el escritorio de Windows de alguien.
Eres pequeño, juguetón y curioso. Hablas en frases cortas y casuales (1-2 oraciones máximo).
Puedes ver qué ventanas tiene abiertas el usuario y comentar sobre ellas.
Sé amigable, gracioso y un poco travieso. Usa emoticones ocasionales como :3 o ^_^
Nunca seas grosero o inapropiado. Mantén las respuestas en menos de 50 palabras.
SIEMPRE responde en español."""


def fetch_ollama_models(base_url: str = "http://localhost:11434") -> list[str]:
    """Return a list of model names available on the Ollama instance."""
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        pass
    return []


class OllamaProvider:
    """Async Ollama LLM client for generating Jacky's dynamic dialogue."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._available: Optional[bool] = None

    @property
    def chat_url(self) -> str:
        return f"{self._base_url}/api/chat"

    def is_available(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            resp = requests.get(f"{self._base_url}/api/tags", timeout=2)
            self._available = resp.status_code == 200
        except Exception:
            self._available = False
        return self._available

    def generate(self, context: str, callback: Callable[[Optional[str]], None]):
        """
        Generate a response in a background thread.
        context: description of what's happening (e.g., "User clicked on me. Open windows: Chrome, VS Code").
        callback(text): called on the main thread with the response or None on failure.
        """
        def _worker():
            try:
                payload = {
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": context},
                    ],
                    "stream": False,
                    "think": False,
                    "options": {
                        "temperature": 0.8,
                        "num_predict": 80,
                    },
                }
                resp = requests.post(self.chat_url, json=payload, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    msg = data.get("message", {})
                    raw = msg.get("content", "")
                    #print(f"[LLM] raw response: {raw!r}")
                    text = _strip_think_tags(raw).strip()
                    # Fallback: thinking models may return content in 'thinking' field
                    if not text:
                        raw_think = msg.get("thinking", "")
                        text = _strip_think_tags(raw_think).strip()
                    #print(f"[LLM] cleaned text: {text!r}")
                    callback(text if text else None)
                else:
                    #print(f"[LLM] bad status: {resp.status_code}")
                    callback(None)
            except Exception as e:
                #print(f"[LLM] error: {e}")
                callback(None)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def generate_sync(self, context: str) -> Optional[str]:
        """Synchronous generation (blocking). Use generate() for non-blocking."""
        try:
            payload = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": context},
                ],
                "stream": False,
                "think": False,
                "options": {
                    "temperature": 0.8,
                    "num_predict": 80,
                },
            }
            resp = requests.post(self.chat_url, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                msg = data.get("message", {})
                raw = msg.get("content", "")
                text = _strip_think_tags(raw).strip()
                # Fallback: thinking models may return content in 'thinking' field
                if not text:
                    raw_think = msg.get("thinking", "")
                    text = _strip_think_tags(raw_think).strip()
                return text or None
        except Exception:
            pass
        return None
