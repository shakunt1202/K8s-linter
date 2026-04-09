"""
AI Provider abstraction layer.

Defines the common interface all providers must implement, plus a
registry for dynamic provider selection at runtime.

Supported providers:
  - anthropic   → Claude (Sonnet, Opus, Haiku)
  - ollama      → Local models via Ollama (llama3, mistral, codellama, etc.)
  - openai      → OpenAI GPT models (gpt-4o, gpt-4-turbo, etc.)
  - openai-compat → Any OpenAI-compatible endpoint (Together, Groq, LM Studio, etc.)
  - mock        → No-op provider for testing / dry-runs
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Type

logger = logging.getLogger(__name__)


# ── Provider response ────────────────────────────────────────────────────────

@dataclass
class ProviderResponse:
    text: str
    model: str
    provider: str
    input_tokens: int  = 0
    output_tokens: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Base provider ────────────────────────────────────────────────────────────

class BaseProvider(ABC):
    """
    All AI providers implement this interface.
    Each call is a single-turn: system prompt + user message → response text.
    """

    name: str = "base"

    def __init__(self, model: str, **kwargs):
        self.model = model
        self.kwargs = kwargs

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
    ) -> ProviderResponse:
        """Synchronous completion. Called from an executor in async context."""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model!r})"


# ── Provider registry ────────────────────────────────────────────────────────

_REGISTRY: Dict[str, Type[BaseProvider]] = {}


def register(name: str):
    """Decorator to register a provider class under a short name."""
    def decorator(cls: Type[BaseProvider]):
        _REGISTRY[name] = cls
        cls.name = name
        return cls
    return decorator


def get_provider(
    provider_name: str,
    model: str,
    **kwargs,
) -> BaseProvider:
    """
    Instantiate a provider by name.

    Examples:
        get_provider("anthropic", "claude-sonnet-4-20250514")
        get_provider("ollama",    "llama3",  base_url="http://localhost:11434")
        get_provider("openai",    "gpt-4o",  api_key="sk-...")
        get_provider("openai-compat", "mixtral-8x7b", base_url="https://api.together.xyz/v1", api_key="...")
        get_provider("mock",      "fake-model")
    """
    cls = _REGISTRY.get(provider_name)
    if cls is None:
        available = ", ".join(_REGISTRY.keys())
        raise ValueError(
            f"Unknown provider '{provider_name}'. Available: {available}"
        )
    return cls(model=model, **kwargs)


def list_providers() -> list[str]:
    return sorted(_REGISTRY.keys())
