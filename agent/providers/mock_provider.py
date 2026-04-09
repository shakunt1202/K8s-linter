"""
Mock provider — returns canned responses for testing and dry runs.
No network calls, no API keys, instant responses.
"""

from __future__ import annotations

from agent.providers import BaseProvider, ProviderResponse, register


@register("mock")
class MockProvider(BaseProvider):
    """
    Returns deterministic fake responses.
    Used when --no-ai-remediation is set or in unit tests.
    """

    DEFAULT_MODEL = "mock-model"

    def __init__(self, model: str = DEFAULT_MODEL, **kwargs):
        super().__init__(model=model or self.DEFAULT_MODEL, **kwargs)

    def complete(self, system: str, user: str, max_tokens: int = 512) -> ProviderResponse:
        # Produce a plausible-looking but fake remediation
        if "remediation" in system.lower():
            text = (
                "[Mock AI] Remediation not available in dry-run mode.\n"
                "Enable a real provider with --provider anthropic|ollama|openai."
            )
        else:
            text = "[Mock AI] Summary not available in dry-run mode."

        return ProviderResponse(
            text=text,
            model=self.model,
            provider="mock",
            input_tokens=0,
            output_tokens=0,
        )
