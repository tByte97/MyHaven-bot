"""Спільні фабрики для тестів BotServices без мережі й без AI-моделей."""
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from telegrambot.backend_client import ApiResult
from telegrambot.bot_config import BotConfig
from telegrambot.handlers import BotServices
from telegrambot.storage import LinkStore, LinkedAccount

TELEGRAM_USER_ID = 4242


def make_config(**overrides):
    values = dict(
        bot_token="test-token",
        api_base_url="http://backend.test",
        link_endpoint="/api/users/telegram/link",
        webapp_url="https://app.test",
        data_dir=Path(tempfile.mkdtemp()),
        request_timeout=5.0,
        gemini_api_key="",
        ai_provider="ollama",
        whisper_model="tiny",
        ollama_url="http://ollama.test",
        ollama_model="test",
    )
    values.update(overrides)
    return BotConfig(**values)


def make_services(linked=True, config=None):
    config = config or make_config()
    store = LinkStore(config.data_dir / "links.json")
    if linked:
        store.save(LinkedAccount(
            telegram_user_id=TELEGRAM_USER_ID,
            telegram_username="tester",
            access_token="access",
            refresh_token="refresh",
            linked_at=LinkStore.now_iso(),
        ))
    client = MagicMock()
    client.request = AsyncMock(return_value=ApiResult(status_code=200, data={"detail": "ok"}, error=None))
    client.refresh_access = AsyncMock(return_value=None)
    with patch("telegrambot.handlers.AIProcessor") as ai_cls:
        services = BotServices(config, store, client)
    ai = ai_cls.return_value
    ai.parse_intent = AsyncMock(return_value={"action": "unknown"})
    return services, client, ai


def make_update(text=None, voice=None):
    update = MagicMock()
    update.effective_user.id = TELEGRAM_USER_ID
    update.effective_user.username = "tester"
    update.message.text = text
    update.message.voice = voice
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    update.message.delete = AsyncMock()
    return update


def replies(update):
    return [call.args[0] for call in update.message.reply_text.await_args_list]
