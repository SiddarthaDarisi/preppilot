"""Abstract LLM provider interface + robust JSON extraction."""
from __future__ import annotations

import abc
import json
import logging
import re
from typing import Optional

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("preppilot.providers")


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a usable completion."""


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def strip_think(text: str) -> str:
    """Strip <think>...</think> reasoning blocks from a plain-text completion
    (for calls that don't go through complete_json's JSON extraction)."""
    return _THINK_RE.sub("", text).strip()


def extract_json_block(text: str) -> str:
    """Extract the first JSON object from possibly-noisy LLM output.

    Strips <think>...</think> blocks (reasoning models), markdown fences,
    then finds the first balanced {...} block.
    """
    cleaned = _THINK_RE.sub("", text).strip()
    fence = _FENCE_RE.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    start = cleaned.find("{")
    if start == -1:
        raise ProviderError(f"No JSON object found in output: {text[:200]!r}")
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : i + 1]
    # Unbalanced — return from first brace and let json.loads report the error
    return cleaned[start:]


class LLMProvider(abc.ABC):
    """Synchronous LLM provider. Callers wrap in asyncio.to_thread as needed."""

    name: str = "base"
    model: str = ""

    @abc.abstractmethod
    def complete(
        self,
        system: str,
        messages: list[dict],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.4,
        think: Optional[bool] = None,
    ) -> str:
        """Return the raw text completion for a chat exchange.

        `think`: None = provider default (unchanged behavior); False = skip
        extended reasoning where the provider supports it (Ollama's hybrid
        thinking models) — used for fast, templated calls like question
        generation where the reasoning trace is discarded anyway. Providers
        without a thinking-mode toggle (Anthropic, OpenAI, fake) ignore it.
        """

    def complete_json(
        self,
        system: str,
        messages: list[dict],
        *,
        schema_model: type[BaseModel],
        temperature: float = 0.4,
        think: Optional[bool] = None,
    ) -> BaseModel:
        """Complete and parse into `schema_model`, retrying once on failure."""
        schema = schema_model.model_json_schema()
        convo = list(messages)
        last_error: Exception | None = None
        for attempt in range(2):
            raw = self.complete(
                system, convo, json_schema=schema, temperature=temperature, think=think
            )
            try:
                block = extract_json_block(raw)
                data = json.loads(block)
                return schema_model.model_validate(data)
            except (ProviderError, json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                logger.warning(
                    "JSON parse/validation failed for %s (attempt %d): %s",
                    schema_model.__name__, attempt + 1, exc,
                )
                if attempt == 0:
                    convo = convo + [
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": (
                                "Your previous response was not valid JSON matching the "
                                f"required schema. Error: {exc}. Respond again with ONLY a "
                                "single strict JSON object matching this schema, no prose, "
                                f"no markdown fences:\n{json.dumps(schema)}"
                            ),
                        },
                    ]
        raise ProviderError(
            f"{self.name} failed to produce valid {schema_model.__name__} JSON: {last_error}"
        )
