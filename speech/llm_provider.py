import json
import logging
import re
import time
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

    def generate_with_image(self, context: str, image_b64: str,
                            callback: Callable[[Optional[str]], None]):
        """Generate a response with an image in a background thread.

        If the model doesn't support vision the request will fail; in that case
        we automatically retry without the image (text-only fallback).
        """
        def _worker():
            try:
                payload = self._build_payload(context)
                # Inject base64 image into the user message (Ollama multimodal format)
                payload["messages"][-1]["images"] = [image_b64]
                resp = requests.post(self.chat_url, json=payload, timeout=60)
                if resp.status_code == 200:
                    data = resp.json()
                    msg = data.get("message", {})
                    raw = msg.get("content", "")
                    text = _strip_think_tags(raw).strip()
                    if not text:
                        raw_think = msg.get("thinking", "")
                        text = _strip_think_tags(raw_think).strip()
                    callback(text if text else None)
                else:
                    # Vision likely unsupported — fallback to text-only
                    log.warning("Ollama vision failed (HTTP %d), retrying text-only",
                                resp.status_code)
                    self.generate(context, callback)
            except Exception as e:
                log.warning("Ollama vision error: %s — retrying text-only", e)
                self.generate(context, callback)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()


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

    def generate_with_image(self, context: str, image_b64: str,
                            callback: Callable[[Optional[str]], None]):
        """Generate a response with an image (OpenAI vision format).

        If the model doesn't support vision the request will fail; in that case
        we automatically retry without the image (text-only fallback).
        """
        def _worker():
            import time
            t0 = time.monotonic()
            try:
                payload = self._build_payload(context)
                # Replace plain text content with multimodal content array
                payload["messages"][-1]["content"] = [
                    {"type": "text", "text": context},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{image_b64}",
                    }},
                ]
                resp = requests.post(
                    self.API_URL,
                    headers=self._headers(),
                    data=json.dumps(payload),
                    timeout=60,
                )
                elapsed = time.monotonic() - t0
                if resp.status_code == 200:
                    text = self._parse_response(resp.json())
                    log.debug("OpenRouter vision OK %.1fs text=%r",
                              elapsed, text[:80] if text else None)
                    callback(text)
                else:
                    # Vision likely unsupported — fallback to text-only
                    log.warning("OpenRouter vision failed (HTTP %d after %.1fs): %s — retrying text-only",
                                resp.status_code, elapsed, resp.text[:200])
                    self.generate(context, callback)
            except Exception as e:
                elapsed = time.monotonic() - t0
                log.warning("OpenRouter vision error after %.1fs: %s — retrying text-only",
                            elapsed, e)
                self.generate(context, callback)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()


class GroqKeyManager:
    """Round-robin key rotation for Groq API keys with per-key cooldown."""

    _DEFAULT_COOLDOWN = 60.0  # seconds

    def __init__(self, api_keys: list[str], cooldown_s: float = _DEFAULT_COOLDOWN):
        if not api_keys:
            raise ValueError("GroqKeyManager requires at least one API key")
        self._cooldown_s = cooldown_s
        self._lock = threading.Lock()
        self._slots: list[dict] = [
            {"key": k, "available": True, "last_used": 0.0}
            for k in api_keys
        ]
        self._index = 0
        log.info("GroqKeyManager initialised with %d key(s)", len(self._slots))

    def get_next_key(self) -> str:
        """Return the next available key (round-robin). Force-resets oldest if all cooling."""
        with self._lock:
            n = len(self._slots)
            for i in range(n):
                idx = (self._index + i) % n
                slot = self._slots[idx]
                if slot["available"]:
                    self._index = (idx + 1) % n
                    slot["last_used"] = time.monotonic()
                    return slot["key"]

            # All keys cooling — force-reset the oldest
            log.warning("GroqKeyManager: all keys cooling, force-resetting oldest")
            oldest = min(self._slots, key=lambda s: s["last_used"])
            oldest["available"] = True
            oldest["last_used"] = time.monotonic()
            return oldest["key"]

    def mark_rate_limited(self, key: str) -> None:
        """Disable a key for *cooldown_s* seconds after a 429."""
        with self._lock:
            slot = next((s for s in self._slots if s["key"] == key), None)
            if not slot:
                return
            log.warning("GroqKeyManager: key ...%s rate-limited, cooldown %.0fs",
                        key[-6:], self._cooldown_s)
            slot["available"] = False

        def _restore():
            with self._lock:
                slot["available"] = True
                log.info("GroqKeyManager: key ...%s available again", key[-6:])

        timer = threading.Timer(self._cooldown_s, _restore)
        timer.daemon = True
        timer.start()

    @property
    def available_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._slots if s["available"])


class GroqProvider:
    """Groq API client with multi-key rotation."""

    API_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_keys: list[str] | None = None,
                 model: str = "meta-llama/llama-4-scout-17b-16e-instruct",
                 pet_name: str = "Jacky"):
        self._api_keys = [k for k in (api_keys or []) if k]
        self._model = model
        self._pet_name = pet_name
        self._available: Optional[bool] = None
        self._key_manager: Optional[GroqKeyManager] = None
        if self._api_keys:
            self._key_manager = GroqKeyManager(self._api_keys)

    def is_available(self) -> bool:
        self._available = self._key_manager is not None and self._key_manager.available_count > 0
        return self._available

    def _headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, context: str) -> dict:
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
        try:
            msg = data["choices"][0]["message"]
            raw = msg.get("content", "") or ""
            text = _strip_think_tags(raw).strip()
            return text or None
        except (KeyError, IndexError):
            return None

    def _do_request(self, payload: dict, timeout: int = 30) -> Optional[str]:
        """Fire a request, handle 429 with one retry on the next key."""
        if not self._key_manager:
            return None
        key = self._key_manager.get_next_key()
        try:
            resp = requests.post(self.API_URL, headers=self._headers(key),
                                 data=json.dumps(payload), timeout=timeout)
            if resp.status_code == 200:
                return self._parse_response(resp.json())
            if resp.status_code == 429:
                self._key_manager.mark_rate_limited(key)
                # Retry once with next key
                key2 = self._key_manager.get_next_key()
                resp2 = requests.post(self.API_URL, headers=self._headers(key2),
                                      data=json.dumps(payload), timeout=timeout)
                if resp2.status_code == 200:
                    return self._parse_response(resp2.json())
                if resp2.status_code == 429:
                    self._key_manager.mark_rate_limited(key2)
                log.warning("Groq retry also failed (HTTP %d)", resp2.status_code)
                return None
            log.warning("Groq HTTP %d: %s", resp.status_code, resp.text[:200])
            return None
        except Exception as e:
            log.warning("Groq request error: %s", e)
            return None

    def generate(self, context: str, callback: Callable[[Optional[str]], None]):
        def _worker():
            t0 = time.monotonic()
            payload = self._build_payload(context)
            text = self._do_request(payload)
            elapsed = time.monotonic() - t0
            log.debug("Groq OK %.1fs text=%r", elapsed, text[:80] if text else None)
            callback(text)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def generate_sync(self, context: str) -> Optional[str]:
        payload = self._build_payload(context)
        return self._do_request(payload)

    def generate_with_image(self, context: str, image_b64: str,
                            callback: Callable[[Optional[str]], None]):
        def _worker():
            t0 = time.monotonic()
            payload = self._build_payload(context)
            payload["messages"][-1]["content"] = [
                {"type": "text", "text": context},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{image_b64}",
                }},
            ]
            text = self._do_request(payload, timeout=60)
            elapsed = time.monotonic() - t0
            if text:
                log.debug("Groq vision OK %.1fs text=%r", elapsed, text[:80] if text else None)
                callback(text)
            else:
                log.warning("Groq vision failed after %.1fs — retrying text-only", elapsed)
                self.generate(context, callback)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()


def create_llm_provider(config: dict):
    """Factory: return the correct provider based on config['llm_provider']."""
    provider = config.get("llm_provider", "ollama")
    pet_name = config.get("pet_name", "Jacky")
    if provider == "groq":
        return GroqProvider(
            api_keys=config.get("groq_api_keys", []),
            model=config.get("groq_model", "meta-llama/llama-4-scout-17b-16e-instruct"),
            pet_name=pet_name,
        )
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
