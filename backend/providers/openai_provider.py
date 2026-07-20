"""OpenAI Chat Completions provider (cloud fallback)."""
from __future__ import annotations

import logging
from typing import Optional

from backend.providers.base import LLMProvider, ProviderError

logger = logging.getLogger("preppilot.providers.openai")


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        try:
            import openai  # lazy: app must run without the SDK installed
        except ImportError as exc:
            raise ProviderError("openai SDK not installed — pip install openai") from exc
        self.model = model
        self._client = openai.OpenAI(api_key=api_key)

    def complete(
        self,
        system: str,
        messages: list[dict],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.4,
        think: Optional[bool] = None,  # no thinking-mode toggle on this provider — ignored
    ) -> str:
        kwargs: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        # gpt-5 family rejects non-default temperature — omit it entirely.
        if not self.model.startswith("gpt-5"):
            kwargs["temperature"] = temperature
        if json_schema is not None:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # SDK raises its own hierarchy
            raise ProviderError(f"OpenAI request failed: {exc}") from exc
        content = response.choices[0].message.content
        if not content:
            raise ProviderError("OpenAI returned empty content")
        return content
