"""Provider factory — honors settings.llm.provider with graceful fallback."""
from __future__ import annotations

import logging

from backend.config import Settings
from backend.providers.base import LLMProvider, ProviderError
from backend.providers.fake_provider import FakeProvider
from backend.providers.ollama_provider import OllamaProvider

logger = logging.getLogger("preppilot.providers.factory")


def _build_cloud(name: str, model: str, settings: Settings) -> LLMProvider:
    if name == "anthropic":
        from backend.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings.anthropic_api_key, model or settings.anthropic.model)
    if name == "openai":
        from backend.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(settings.openai_api_key, model or settings.openai.model)
    raise ProviderError(f"Unknown cloud provider: {name!r}")


def _has_key(name: str, settings: Settings) -> bool:
    if name == "anthropic":
        return bool(settings.anthropic_api_key)
    if name == "openai":
        return bool(settings.openai_api_key)
    return False


def get_provider(settings: Settings) -> LLMProvider:
    """Build the configured provider, falling back if ollama is unreachable."""
    name = settings.llm.provider
    if name == "fake":
        return FakeProvider()
    if name in ("anthropic", "openai"):
        return _build_cloud(name, "", settings)
    if name == "ollama":
        provider = OllamaProvider(settings.llm.base_url, settings.llm.model, settings.llm.keep_alive)
        if provider.health_check():
            return provider
        fallback = settings.llm.fallback_provider
        if fallback and _has_key(fallback, settings):
            logger.warning(
                "Ollama at %s is unreachable — falling back to %s (%s).",
                settings.llm.base_url, fallback,
                settings.llm.fallback_model or "default model",
            )
            try:
                return _build_cloud(fallback, settings.llm.fallback_model, settings)
            except ProviderError as exc:
                logger.warning("Fallback provider %s failed to initialize: %s", fallback, exc)
        logger.warning(
            "Ollama at %s is unreachable and no usable fallback (provider=%r, key present=%s) — "
            "using the FAKE provider. Responses are canned; start Ollama or set an API key.",
            settings.llm.base_url, fallback, _has_key(fallback, settings),
        )
        return FakeProvider()
    raise ProviderError(f"Unknown LLM provider: {name!r}")
