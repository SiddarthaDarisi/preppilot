"""Anthropic provider (premium coaching) with prompt caching."""
from __future__ import annotations

import logging
from typing import Optional

from backend.providers.base import LLMProvider, ProviderError

logger = logging.getLogger("preppilot.providers.anthropic")


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        try:
            import anthropic  # lazy: app must run without the SDK installed
        except ImportError as exc:
            raise ProviderError(
                "anthropic SDK not installed — pip install anthropic"
            ) from exc
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(
        self,
        system: str,
        messages: list[dict],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.4,
        think: Optional[bool] = None,  # no thinking-mode toggle on this provider — ignored
    ) -> str:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=2048,
                temperature=temperature,
                system=[
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=messages,
            )
        except Exception as exc:  # SDK raises its own hierarchy
            raise ProviderError(f"Anthropic request failed: {exc}") from exc
        parts = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        if not parts:
            raise ProviderError("Anthropic returned no text content")
        return "".join(parts)
