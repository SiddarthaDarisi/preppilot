"""Ollama chat provider (local-first)."""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from backend.providers.base import LLMProvider, ProviderError

logger = logging.getLogger("preppilot.providers.ollama")


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, keep_alive: str = "30m") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.keep_alive = keep_alive
        # Some older Ollama builds reject the "think" field entirely; once we
        # learn that, stop sending it rather than eating a 400 every call.
        self._think_supported = True

    def health_check(self) -> bool:
        """Cheap reachability check against the Ollama server."""
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=2.0)
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            logger.debug("Ollama health check failed: %s", exc)
            return False

    def _build_payload(
        self, system: str, messages: list[dict], json_schema: dict | None,
        temperature: float, think: Optional[bool],
    ) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": False,
            "options": {"temperature": temperature},
            "keep_alive": self.keep_alive,
        }
        if json_schema is not None:
            payload["format"] = "json"
        if think is not None and self._think_supported:
            payload["think"] = think
        return payload

    def complete(
        self,
        system: str,
        messages: list[dict],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.4,
        think: Optional[bool] = None,
    ) -> str:
        payload = self._build_payload(system, messages, json_schema, temperature, think)
        try:
            resp = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=120.0)
            if resp.status_code == 400 and "think" in payload and "think" in resp.text.lower():
                # This Ollama version doesn't understand "think" — drop it and retry once.
                logger.warning("Ollama rejected 'think' param; disabling it for this process")
                self._think_supported = False
                payload = self._build_payload(system, messages, json_schema, temperature, think)
                resp = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=120.0)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc
        data = resp.json()
        content = (data.get("message") or {}).get("content", "")
        if not content:
            raise ProviderError(f"Ollama returned empty content: {data!r:.200}")
        return content
