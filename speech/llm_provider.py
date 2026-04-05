import json
import logging
import re
import threading
from typing import Optional, Callable

import requests

log = logging.getLogger("llm_provider")


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks produced by reasoning models (e.g. Qwen3)."""
    return re.sub(r"<think>[\s\S]*?</think>", "", text).strip()


def build_system_prompt(pet_name: str = "Jacky") -> str:
    """Build the LLM system prompt with the pet's actual name."""
    return f"""Eres {pet_name}, una mascota virtual humanoide chibi que vive en el escritorio de Windows de alguien.
Eres pequeño, juguetón y curioso. Hablas en frases cortas y casuales (1-2 oraciones máximo).
Si se te menciona una ventana o app, haz UN solo comentario puntual sobre ella. No enumeres ni menciones otras ventanas.
No menciones la hora a menos que la situación lo pida explícitamente.
Sé amigable, gracioso y un poco travieso. Usa emoticones ocasionales como :3 o ^_^
Mantén las respuestas en menos de 50 palabras.
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

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3", pet_name: str = "Jacky"):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._pet_name = pet_name
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

    def _build_payload(self, context: str) -> dict:
        """Build the Ollama chat payload for the given context."""
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": build_system_prompt(self._pet_name)},
                {"role": "user", "content": context},
            ],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.8,
                "num_predict": 80,
            },
        }

    def generate(self, context: str, callback: Callable[[Optional[str]], None]):
        """
        Generate a response in a background thread.
        context: description of what's happening (e.g., "User clicked on me. Open windows: Chrome, VS Code").
        callback(text): called on the main thread with the response or None on failure.
        """
        def _worker():
            try:
                payload = self._build_payload(context)
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
            payload = self._build_payload(context)
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


class OpenRouterProvider:
    """OpenRouter API client — works with any model available on openrouter.ai."""

    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: str = "", model: str = "qwen/qwen3.6-plus:free", pet_name: str = "Jacky"):
        self._api_key = api_key
        self._model = model
        self._pet_name = pet_name
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """Check if the API key is set (basic validation)."""
        self._available = bool(self._api_key)
        return self._available

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, context: str) -> dict:
        """Build the OpenRouter chat completion payload for the given context."""
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": build_system_prompt(self._pet_name)},
                {"role": "user", "content": context},
            ],
            "temperature": 0.8,
            "max_tokens": 120,
        }

    def _parse_response(self, data: dict) -> Optional[str]:
        """Extract text from an OpenRouter chat completion response."""
        try:
            msg = data["choices"][0]["message"]
            raw = msg.get("content", "") or ""
            text = _strip_think_tags(raw).strip()
            return text or None
        except (KeyError, IndexError):
            return None

    def generate(self, context: str, callback: Callable[[Optional[str]], None]):
        """Generate a response in a background thread (same interface as OllamaProvider)."""
        def _worker():
            import time
            t0 = time.monotonic()
            try:
                payload = self._build_payload(context)
                resp = requests.post(
                    self.API_URL,
                    headers=self._headers(),
                    data=json.dumps(payload),
                    timeout=30,
                )
                elapsed = time.monotonic() - t0
                if resp.status_code == 200:
                    text = self._parse_response(resp.json())
                    log.debug("OpenRouter OK %.1fs text=%r", elapsed, text[:80] if text else None)
                    callback(text)
                else:
                    log.warning("OpenRouter HTTP %d after %.1fs: %s",
                                resp.status_code, elapsed, resp.text[:200])
                    callback(None)
            except Exception as e:
                elapsed = time.monotonic() - t0
                log.warning("OpenRouter error after %.1fs: %s", elapsed, e)
                callback(None)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def generate_sync(self, context: str) -> Optional[str]:
        """Synchronous generation (blocking)."""
        try:
            payload = self._build_payload(context)
            resp = requests.post(
                self.API_URL,
                headers=self._headers(),
                data=json.dumps(payload),
                timeout=30,
            )
            if resp.status_code == 200:
                return self._parse_response(resp.json())
        except Exception:
            pass
        return None


def create_llm_provider(config: dict):
    """Factory: return the correct provider based on config['llm_provider']."""
    provider = config.get("llm_provider", "ollama")
    pet_name = config.get("pet_name", "Jacky")
    if provider == "openrouter":
        return OpenRouterProvider(
            api_key=config.get("openrouter_api_key", ""),
            model=config.get("openrouter_model", "qwen/qwen3.6-plus:free"),
            pet_name=pet_name,
        )
    return OllamaProvider(
        base_url=config.get("ollama_url", "http://localhost:11434"),
        model=config.get("ollama_model", "llama3"),
        pet_name=pet_name,
    )
