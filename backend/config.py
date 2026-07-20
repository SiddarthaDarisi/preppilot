"""PrepPilot settings — loads config.yaml, overridable via PREPPILOT_* env vars.

Usage:
    from backend.config import get_settings
    settings = get_settings()
    settings.llm.provider  # "ollama"
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("PREPPILOT_CONFIG", PROJECT_ROOT / "config.yaml"))


class LLMConfig(BaseModel):
    provider: str = "ollama"  # ollama | anthropic | openai
    model: str = "qwen3:8b"
    temperature: float = 0.4
    base_url: str = "http://localhost:11434"
    fallback_provider: str = ""
    fallback_model: str = ""
    # Ollama-only: keeps qwen3 resident between turns so a follow-up call
    # doesn't pay a reload cost (OLLAMA_MAX_LOADED_MODELS=1 still applies).
    keep_alive: str = "30m"


class AnthropicConfig(BaseModel):
    model: str = "claude-haiku-4-5"


class OpenAIConfig(BaseModel):
    model: str = "gpt-5-mini"


class STTConfig(BaseModel):
    backend: str = "faster-whisper"  # faster-whisper | none
    model: str = "large-v3"
    compute_type: str = "int8_float16"
    device: str = "cuda"
    # Load the whisper model onto the GPU at server startup instead of on the
    # first utterance, so the first voice turn isn't slowed by a model load.
    preload: bool = True


class VADConfig(BaseModel):
    backend: str = "silero"  # silero | none
    end_of_turn_silence_ms: int = 1000
    chunk_ms: int = 200
    # Patience window for Full Interview mode's hands-free auto end-of-turn
    # (the practice tab disables auto end-of-turn entirely — see set_options).
    full_mode_silence_ms: int = 2500


class TTSConfig(BaseModel):
    backend: str = "kokoro"  # kokoro | none
    # af_heart: Kokoro's most natural-sounding voice (American female) — the
    # default am_adam read as a harsh, hard-to-parse deep male voice.
    # Other easy options: af_bella, af_nicole, af_sarah (female), bf_emma (British female).
    voice: str = "af_heart"
    lang_code: str = "a"


class AnalyticsConfig(BaseModel):
    use_ser: bool = False
    filler_target_rate: float = 0.03
    wpm_range: tuple[int, int] = (110, 160)


class SessionConfig(BaseModel):
    max_questions: int = 8
    followup_score_threshold: int = 6


class DBConfig(BaseModel):
    url: str = "sqlite:///preppilot.db"


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])


class Settings(BaseSettings):
    """Priority: env vars (PREPPILOT_*) > .env > config.yaml > defaults."""

    model_config = SettingsConfigDict(
        env_prefix="PREPPILOT_", env_nested_delimiter="__", extra="ignore"
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        def yaml_source() -> dict:
            return _load_yaml(CONFIG_PATH)

        # env outranks yaml; yaml outranks field defaults
        return (init_settings, env_settings, dotenv_settings, yaml_source, file_secret_settings)

    llm: LLMConfig = Field(default_factory=LLMConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    vad: VADConfig = Field(default_factory=VADConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    db: DBConfig = Field(default_factory=DBConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)

    # API keys come from env / .env only
    anthropic_api_key: str = ""
    openai_api_key: str = ""


def _load_yaml(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@lru_cache
def get_settings() -> Settings:
    settings = Settings()  # sources: env > .env > config.yaml > defaults
    # Conventional env names also honored
    settings.anthropic_api_key = settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    settings.openai_api_key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
    return settings
