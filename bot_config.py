from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import os


@dataclass(frozen=True)
class BotConfig:
    """Конфігурація запуску Telegram bot."""

    bot_token: str
    api_base_url: str
    link_endpoint: Optional[str]
    webapp_url: Optional[str]
    data_dir: Path
    request_timeout: float
    gemini_api_key: str
    ai_provider: str
    whisper_model: str
    ollama_url: str
    ollama_model: str

@dataclass(frozen=True)
class AiConfig:
    """Конфігурація AI processor."""

    provider: str
    gemini_api_key: str
    ollama_url: str
    ollama_model: str
    whisper_model_size: str


# Функції

def _clean_url(value: str) -> str:
    return value.rstrip("/")


def load_config() -> BotConfig:
    # Завантажує конфігурацію зі змінних середовища.

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required.")

    api_base_url = _clean_url(
        os.getenv("MYHAVEN_API_BASE_URL", "http://localhost:8000").strip()
    )

    link_endpoint = os.getenv("TELEGRAM_LINK_ENDPOINT", "").strip() or None
    if link_endpoint:
        link_endpoint = link_endpoint.rstrip("/")

    webapp_url = os.getenv("TELEGRAM_WEBAPP_URL", "").strip() or None

    data_dir = Path(os.getenv("BOT_DATA_DIR", "./data"))

    timeout_value = os.getenv("REQUEST_TIMEOUT_SECONDS", "15").strip() or "15"
    request_timeout = float(timeout_value)

    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    ai_provider    = os.getenv("AI_PROVIDER", "gemini").strip()
    whisper_model  = os.getenv("WHISPER_MODEL", "medium").strip()
    ollama_url     = os.getenv("OLLAMA_URL", "http://localhost:11434").strip()
    ollama_model   = os.getenv("OLLAMA_MODEL", "llama3.1:8b").strip()


    return BotConfig(
        bot_token=bot_token,
        api_base_url=api_base_url,
        link_endpoint=link_endpoint,
        webapp_url=webapp_url,
        data_dir=data_dir,
        request_timeout=request_timeout,
        gemini_api_key=gemini_api_key,
        ai_provider=ai_provider,
        whisper_model=whisper_model,
        ollama_url=ollama_url,
        ollama_model=ollama_model,
    )
