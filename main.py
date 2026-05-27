from pathlib import Path
import logging
import sys

from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, ContextTypes
from telegram import Update

if not __package__:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from telegrambot.backend_client import BackendClient
from telegrambot.bot_config import load_config
from telegrambot.handlers import BotServices, register_handlers
from telegrambot.storage import LinkStore


def _configure_logging() -> None:
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "bot.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.exception("Unhandled exception", exc_info=context.error)


def main() -> None:
    # Точка входу для Telegram bot.

    _configure_logging()
    load_dotenv()
    config = load_config()

    store = LinkStore(config.data_dir / "links.json")
    backend_client = BackendClient(
        config.api_base_url,
        timeout=config.request_timeout,
    )

    services = BotServices(config, store, backend_client)
    application = ApplicationBuilder().token(config.bot_token).build()
    register_handlers(application, services)
    application.add_error_handler(_on_error)

    logging.getLogger(__name__).info("Bot started")
    logging.getLogger(__name__).info("Bot data dir: %s", config.data_dir)

    application.run_polling()


if __name__ == "__main__":
    main()
