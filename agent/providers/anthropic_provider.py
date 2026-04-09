"""
Anthropic provider — calls Claude via the official anthropic SDK.
The SDK is imported lazily so the provider registers even when not installed.
"""

from __future__ import annotations
import logging
import os
from agent.providers import BaseProvider, ProviderResponse, register

logger = logging.getLogger(__name__)


@register("anthropic")
class AnthropicProvider(BaseProvider):
    """
    Calls Claude via the official Anthropic SDK (lazy import).

    Config:
        model   : claude-sonnet-4-20250514 (default)
        api_key : ANTHROPIC_API_KEY env var (or pass explicitly)
    """
    DEFAULT_MODEL = "claude-sonnet-4-20250514"

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str = "", **kwargs):
        super().__init__(model=model or self.DEFAULT_MODEL, **kwargs)
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._client  = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic as _sdk
            except ImportError:
                raise ImportError(
                    "anthropic package not installed. Run: pip install anthropic"
                )
            self._client = _sdk.Anthropic(
                api_key=self._api_key or None
            )
        return self._client

    def complete(self, system: str, user: str, max_tokens: int = 512) -> ProviderResponse:
        client   = self._get_client()
        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = response.content[0].text.strip()
        return ProviderResponse(
            text=text,
            model=self.model,
            provider="anthropic",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
