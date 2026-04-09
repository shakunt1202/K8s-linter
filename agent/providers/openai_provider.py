"""
OpenAI provider — uses the openai Python SDK.
Also covers any OpenAI-compatible API (Groq, Together AI, LM Studio, Perplexity, etc.)
via the openai-compat provider name.

Install: pip install openai

OpenAI models:   gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo
Groq models:     llama3-70b-8192, mixtral-8x7b-32768, gemma-7b-it
Together models: meta-llama/Llama-3-70b-chat-hf, mistralai/Mixtral-8x7B-Instruct-v0.1
LM Studio:       any locally loaded model (use base_url=http://localhost:1234/v1)

Usage:
  # OpenAI
  python main.py --provider openai --model gpt-4o

  # Groq
  python main.py --provider openai-compat --model llama3-70b-8192 \
    --provider-base-url https://api.groq.com/openai/v1 \
    --provider-api-key $GROQ_API_KEY

  # LM Studio (local)
  python main.py --provider openai-compat --model local-model \
    --provider-base-url http://localhost:1234/v1
"""

from __future__ import annotations

import logging
import os

from agent.providers import BaseProvider, ProviderResponse, register

logger = logging.getLogger(__name__)


class _OpenAIBase(BaseProvider):
    """Shared implementation for openai and openai-compat providers."""

    def __init__(
        self,
        model:    str,
        api_key:  str = "",
        base_url: str = "",
        **kwargs,
    ):
        super().__init__(model=model, **kwargs)
        self._api_key  = api_key
        self._base_url = base_url
        self._client   = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError:
                raise ImportError(
                    "openai package not installed. Run: pip install openai"
                )
            init_kwargs = {}
            key = self._api_key or os.getenv("OPENAI_API_KEY", "")
            if key:
                init_kwargs["api_key"] = key
            if self._base_url:
                init_kwargs["base_url"] = self._base_url
            self._client = OpenAI(**init_kwargs)
        return self._client

    def complete(self, system: str, user: str, max_tokens: int = 512) -> ProviderResponse:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=0.2,
        )
        text = response.choices[0].message.content.strip()
        usage = response.usage
        return ProviderResponse(
            text=text,
            model=self.model,
            provider=self.name,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )


@register("openai")
class OpenAIProvider(_OpenAIBase):
    """
    OpenAI API provider.
    Reads OPENAI_API_KEY from environment by default.

    Config:
        model   : gpt-4o (default)
        api_key : OPENAI_API_KEY env var (or pass explicitly)
    """
    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, model: str = DEFAULT_MODEL, **kwargs):
        super().__init__(model=model or self.DEFAULT_MODEL, **kwargs)


@register("openai-compat")
class OpenAICompatProvider(_OpenAIBase):
    """
    OpenAI-compatible provider for third-party endpoints.
    Requires base_url pointing to the /v1 endpoint.

    Compatible with: Groq, Together AI, LM Studio, Perplexity, Fireworks,
                     Anyscale, DeepInfra, OpenRouter, Mistral AI, and more.

    Config:
        model    : model name as required by the endpoint
        base_url : https://api.groq.com/openai/v1 (example)
        api_key  : provider-specific API key
    """
    DEFAULT_MODEL = "llama3-70b-8192"

    def __init__(self, model: str = DEFAULT_MODEL, **kwargs):
        super().__init__(model=model or self.DEFAULT_MODEL, **kwargs)
