"""
Ollama provider — calls a local Ollama instance via its REST API.

Ollama runs entirely on-premise. No API key required.
Install: https://ollama.com
Pull a model: ollama pull llama3

Supported models (examples):
  llama3, llama3:8b, llama3:70b
  mistral, mistral:7b
  codellama, codellama:13b
  gemma2, phi3, qwen2
  deepseek-coder
  any model available on https://ollama.com/library

Usage:
  python main.py --provider ollama --model llama3 --ollama-url http://localhost:11434
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Any, Dict

from agent.providers import BaseProvider, ProviderResponse, register

logger = logging.getLogger(__name__)

OLLAMA_DEFAULT_URL = "http://localhost:11434"


@register("ollama")
class OllamaProvider(BaseProvider):
    """
    Calls a local Ollama instance using its /api/chat REST endpoint.
    No SDK dependency — uses only stdlib urllib.

    Config:
        model     : llama3 (default)
        base_url  : http://localhost:11434 (default)
        timeout   : 120 seconds (default — local models can be slow)
        options   : dict of Ollama model parameters (temperature, top_p, etc.)
    """

    DEFAULT_MODEL = "llama3"

    def __init__(
        self,
        model:    str  = DEFAULT_MODEL,
        base_url: str  = OLLAMA_DEFAULT_URL,
        timeout:  int  = 120,
        options:  Dict[str, Any] = None,
        **kwargs,
    ):
        super().__init__(model=model or self.DEFAULT_MODEL, **kwargs)
        self.base_url = base_url.rstrip("/")
        self.timeout  = timeout
        self.options  = options or {"temperature": 0.2}

    def complete(self, system: str, user: str, max_tokens: int = 512) -> ProviderResponse:
        """
        Uses /api/chat with roles: system + user.
        Falls back to /api/generate if chat endpoint fails (older Ollama versions).
        """
        try:
            return self._chat(system, user, max_tokens)
        except OllamaError as e:
            if "chat" in str(e).lower():
                logger.warning("Ollama /api/chat failed, trying /api/generate: %s", e)
                return self._generate(system, user, max_tokens)
            raise

    def _chat(self, system: str, user: str, max_tokens: int) -> ProviderResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream": False,
            "options": {**self.options, "num_predict": max_tokens},
        }
        data = self._post("/api/chat", payload)
        text = data.get("message", {}).get("content", "").strip()
        return ProviderResponse(
            text=text,
            model=self.model,
            provider="ollama",
            metadata={"done": data.get("done"), "eval_count": data.get("eval_count", 0)},
        )

    def _generate(self, system: str, user: str, max_tokens: int) -> ProviderResponse:
        """Fallback for older Ollama versions that don't support /api/chat."""
        prompt = f"<system>\n{system}\n</system>\n\n<user>\n{user}\n</user>\n\n<assistant>"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {**self.options, "num_predict": max_tokens},
        }
        data = self._post("/api/generate", payload)
        text = data.get("response", "").strip()
        return ProviderResponse(
            text=text,
            model=self.model,
            provider="ollama",
            metadata={"done": data.get("done"), "eval_count": data.get("eval_count", 0)},
        )

    def _post(self, path: str, payload: dict) -> dict:
        url  = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise OllamaError(f"HTTP {e.code} from Ollama at {url}: {detail}") from e
        except urllib.error.URLError as e:
            raise OllamaError(
                f"Cannot reach Ollama at {self.base_url}. "
                f"Is Ollama running? (ollama serve)  Error: {e.reason}"
            ) from e

    def list_models(self) -> list[str]:
        """Return list of locally available Ollama models."""
        try:
            url = f"{self.base_url}/api/tags"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.warning("Could not list Ollama models: %s", e)
            return []


class OllamaError(RuntimeError):
    pass
