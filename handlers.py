from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional, Dict, Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update, WebAppInfo
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from .backend_client import ApiResult, BackendClient, build_telegram_path
from .bot_config import BotConfig
from .storage import LinkStore, LinkedAccount
from .text_normalization import clean_transaction_description, resolve_spoken_category
from .utils import format_response, parse_kv_args, parse_payload

from telegrambot.ai_processor import AIProcessor

import datetime
import os
import re
import tempfile


MENU_BUTTON = "📋 Меню"
HELP_BUTTON = "ℹ️ Допомога"
EXTRA_BUTTON = "⚙️ Інші дії"
LINK_BUTTON = "🔗 Прив'язати акаунт"
UNLINK_BUTTON = "❌ Відв'язати акаунт"
HEALTH_BUTTON = "🩺 API health"
WEBAPP_BUTTON = "🌐 WebApp"
DASHBOARD_BUTTON = "🏠 Дашборд"
STATISTICS_BUTTON = "📊 Статистика"
CATEGORIES_BUTTON = "🏷 Категорії"
CALENDAR_BUTTON = "📅 Календар"
DAY_BUTTON = "📆 День"
TRANSACTIONS_BUTTON = "💳 Транзакції"
TRANSACTION_DETAIL_BUTTON = "🔎 Транзакція ID"
CREATE_TRANSACTION_BUTTON = "➕ Додати транзакцію"
UPDATE_TRANSACTION_BUTTON = "✏️ Оновити транзакцію"
DELETE_TRANSACTION_BUTTON = "🗑 Видалити транзакцію"
BUDGETS_BUTTON = "💰 Бюджети"
BUDGET_DETAIL_BUTTON = "🔎 Бюджет ID"
CREATE_BUDGET_BUTTON = "➕ Створити бюджет"
UPDATE_BUDGET_BUTTON = "✏️ Оновити бюджет"
DELETE_BUDGET_BUTTON = "🗑 Видалити бюджет"

MAIN_KEYBOARD = [
    [DASHBOARD_BUTTON, TRANSACTIONS_BUTTON],
    [CREATE_TRANSACTION_BUTTON, STATISTICS_BUTTON],
    [BUDGETS_BUTTON, CALENDAR_BUTTON],
    [CATEGORIES_BUTTON, WEBAPP_BUTTON],
    [LINK_BUTTON, HELP_BUTTON],
    [EXTRA_BUTTON, MENU_BUTTON],
]

EXTRA_KEYBOARD = [
    [TRANSACTION_DETAIL_BUTTON, UPDATE_TRANSACTION_BUTTON],
    [DELETE_TRANSACTION_BUTTON, DAY_BUTTON],
    [CREATE_BUDGET_BUTTON, BUDGET_DETAIL_BUTTON],
    [UPDATE_BUDGET_BUTTON, DELETE_BUDGET_BUTTON],
    [HEALTH_BUTTON, UNLINK_BUTTON],
    [MENU_BUTTON],
]


class BotServices:
    """Обробники Telegram bot, підключені до endpoint-ів backend API."""

    def __init__(
        self,
        config: BotConfig,
        store: LinkStore,
        backend_client: BackendClient,
    ) -> None:
        self._config = config
        self._store = store
        self._client = backend_client
        self._log_dir = Path(__file__).resolve().parent / "logs"
        self._log_dir.mkdir(exist_ok=True)
        self._pending_clarifications: Dict[int, Dict[str, Any]] = {}
        self._pending_quick_actions: Dict[int, Dict[str, str]] = {}
        self._ai = AIProcessor(
            whisper_model_size=config.whisper_model,
            provider=config.ai_provider,
            gemini_api_key=config.gemini_api_key,
            ollama_url=config.ollama_url,
            ollama_model=config.ollama_model,
        )


    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Обробляє команду /start.

        if not update.message:
            return
        await update.message.reply_text(
            (
                "Вітаю в MyHaven bot.\n"
                "Користуйся кнопками нижче для швидких дій. "
                "Для прив'язки акаунта натисни кнопку прив'язки й надішли секретний ключ."
            ),
            reply_markup=self._main_keyboard(),
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Показує доступні команди.

        if not update.message:
            return
        await update.message.reply_text(
            (
                "Швидкі дії доступні через кнопки нижче.\n\n"
                "Основні кнопки: дашборд, транзакції, додати транзакцію, статистика, бюджети, календар, категорії, WebApp.\n"
                "Додаткові кнопки: деталі/оновлення/видалення за ID, день календаря, створення й редагування бюджетів, API health, відв'язка акаунта.\n\n"
                "Також можна просто написати природною мовою або надіслати голосове повідомлення, наприклад: "
                "\"додав витрату 250 грн на продукти\".\n"
                "Для імпорту виписки надішли PDF/CSV/XLS/XLSX з підписом bank=ID або bank_name=NAME."
            ),
            reply_markup=self._extra_keyboard(),
        )

    async def link(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Прив'язує користувача Telegram до токенів backend.

        if not update.message or not update.effective_user:
            return

        secret = self._get_args_text(update)
        if not secret:
            await self._prompt_quick_action(
                update,
                "link",
                "Надішли секретний ключ прив'язки акаунта одним повідомленням.",
            )
            return
        await self._link_from_secret(update, secret)

    async def unlink(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Видаляє прив'язку Telegram.

        if not update.message or not update.effective_user:
            return
        self._store.remove(update.effective_user.id)
        await self._reply_text(update, "Прив'язку видалено.")

    async def health(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Викликає /api/telegram/health/.

        result = await self._call_api(update, "GET", build_telegram_path("health"))
        await self._reply_result(update, result)

    async def dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Викликає /api/telegram/dashboard/.

        result = await self._call_api(update, "GET", build_telegram_path("dashboard"))
        await self._reply_result(update, result)

    async def statistics(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Викликає /api/telegram/statistics/.

        params: Dict[str, str] = {}
        if context.args:
            try:
                months = int(context.args[0])
                params["months"] = str(months)
            except (TypeError, ValueError):
                await self._reply_text(update, "Usage: /statistics [months]")
                return

        result = await self._call_api(
            update,
            "GET",
            build_telegram_path("statistics"),
            params=params or None,
        )
        await self._reply_result(update, result)

    async def categories(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Викликає /api/telegram/categories/.

        result = await self._call_api(update, "GET", build_telegram_path("categories"))
        await self._reply_result(update, result)

    async def calendar(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Викликає /api/telegram/calendar/.

        params: Dict[str, str] = {}
        if len(context.args) >= 2:
            try:
                params["year"] = str(int(context.args[0]))
                params["month"] = str(int(context.args[1]))
            except (TypeError, ValueError):
                await self._reply_text(update, "Usage: /calendar [year month]")
                return

        result = await self._call_api(
            update,
            "GET",
            build_telegram_path("calendar"),
            params=params or None,
        )
        await self._reply_result(update, result)

    async def calendar_day(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Викликає /api/telegram/calendar/<year>/<month>/<day>/.

        if len(context.args) < 3:
            await self._reply_text(update, "Usage: /day <year> <month> <day>")
            return
        try:
            year = int(context.args[0])
            month = int(context.args[1])
            day = int(context.args[2])
        except (TypeError, ValueError):
            await self._reply_text(update, "Usage: /day <year> <month> <day>")
            return

        path = build_telegram_path(f"calendar/{year}/{month}/{day}")
        result = await self._call_api(update, "GET", path)
        await self._reply_result(update, result)

    async def transactions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Викликає /api/telegram/transactions/ з фільтрами.

        params = parse_kv_args(self._get_args_text(update))
        result = await self._call_api(
            update,
            "GET",
            build_telegram_path("transactions"),
            params={k: str(v) for k, v in params.items()} or None,
        )
        await self._reply_result(update, result)

    async def transaction_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        # Викликає /api/telegram/transactions/<id>/.

        if not context.args:
            await self._reply_text(update, "Usage: /transaction <id>")
            return
        try:
            transaction_id = int(context.args[0])
        except (TypeError, ValueError):
            await self._reply_text(update, "Usage: /transaction <id>")
            return

        result = await self._call_api(
            update,
            "GET",
            build_telegram_path(f"transactions/{transaction_id}"),
        )
        await self._reply_result(update, result)

    async def transaction_create(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        # Викликає POST /api/telegram/transactions/.

        payload_text = self._get_args_text(update)
        if not payload_text:
            await self._reply_text(update, "Usage: /create_transaction <json|key=value>")
            return

        payload = parse_payload(payload_text)
        path = build_telegram_path("transactions")
        result = await self._call_api(
            update,
            "POST",
            path,
            json=payload,
        )
        await self._reply_result(
            update,
            result,
            retry={
                "action": "create_transaction",
                "method": "POST",
                "path": path,
                "json": payload,
            },
        )

    async def transaction_update(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        # Викликає PATCH /api/telegram/transactions/<id>/.

        if len(context.args) < 2:
            await self._reply_text(update, "Usage: /update_transaction <id> <json|key=value>")
            return

        try:
            transaction_id = int(context.args[0])
        except (TypeError, ValueError):
            await self._reply_text(update, "Usage: /update_transaction <id> <json|key=value>")
            return

        payload_text = " ".join(context.args[1:])
        payload = parse_payload(payload_text)

        result = await self._call_api(
            update,
            "PATCH",
            build_telegram_path(f"transactions/{transaction_id}"),
            json=payload,
        )
        await self._reply_result(update, result)

    async def transaction_delete(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        # Викликає DELETE /api/telegram/transactions/<id>/.

        if not context.args:
            await self._reply_text(update, "Usage: /delete_transaction <id>")
            return

        try:
            transaction_id = int(context.args[0])
        except (TypeError, ValueError):
            await self._reply_text(update, "Usage: /delete_transaction <id>")
            return

        result = await self._call_api(
            update,
            "DELETE",
            build_telegram_path(f"transactions/{transaction_id}"),
        )
        await self._reply_result(update, result)

    async def budgets(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Викликає /api/telegram/budgets/ з необов'язковим місяцем.

        params = parse_kv_args(self._get_args_text(update))
        result = await self._call_api(
            update,
            "GET",
            build_telegram_path("budgets"),
            params={k: str(v) for k, v in params.items()} or None,
        )
        await self._reply_result(update, result)

    async def budget_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        # Викликає /api/telegram/budgets/<id>/.

        if not context.args:
            await self._reply_text(update, "Usage: /budget <id>")
            return

        try:
            budget_id = int(context.args[0])
        except (TypeError, ValueError):
            await self._reply_text(update, "Usage: /budget <id>")
            return

        result = await self._call_api(
            update,
            "GET",
            build_telegram_path(f"budgets/{budget_id}"),
        )
        await self._reply_result(update, result)

    async def budget_create(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        # Викликає POST /api/telegram/budgets/.

        payload_text = self._get_args_text(update)
        if not payload_text:
            await self._reply_text(update, "Usage: /create_budget <json|key=value>")
            return

        payload = parse_payload(payload_text)
        path = build_telegram_path("budgets")
        result = await self._call_api(
            update,
            "POST",
            path,
            json=payload,
        )
        await self._reply_result(
            update,
            result,
            retry={
                "action": "create_budget",
                "method": "POST",
                "path": path,
                "json": payload,
            },
        )

    async def budget_update(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        # Викликає PATCH /api/telegram/budgets/<id>/.

        if len(context.args) < 2:
            await self._reply_text(update, "Usage: /update_budget <id> <json|key=value>")
            return

        try:
            budget_id = int(context.args[0])
        except (TypeError, ValueError):
            await self._reply_text(update, "Usage: /update_budget <id> <json|key=value>")
            return

        payload_text = " ".join(context.args[1:])
        payload = parse_payload(payload_text)

        result = await self._call_api(
            update,
            "PATCH",
            build_telegram_path(f"budgets/{budget_id}"),
            json=payload,
        )
        await self._reply_result(update, result)

    async def budget_delete(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        # Викликає DELETE /api/telegram/budgets/<id>/.

        if not context.args:
            await self._reply_text(update, "Usage: /delete_budget <id>")
            return

        try:
            budget_id = int(context.args[0])
        except (TypeError, ValueError):
            await self._reply_text(update, "Usage: /delete_budget <id>")
            return

        result = await self._call_api(
            update,
            "DELETE",
            build_telegram_path(f"budgets/{budget_id}"),
        )
        await self._reply_result(update, result)

    async def webapp(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Надсилає кнопку WebApp, якщо URL налаштований.

        if not update.message:
            return

        if not self._config.webapp_url:
            await update.message.reply_text("WebApp URL is not configured.")
            return

        webapp_url = self._config.webapp_url
        link = self._require_link(update)
        if link:
            webapp_url = self._build_webapp_url(link.access_token)

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Open WebApp", web_app=WebAppInfo(webapp_url))]]
        )
        await update.message.reply_text("Open MyHaven WebApp:", reply_markup=keyboard)

    def _main_keyboard(self) -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True, is_persistent=True)

    def _extra_keyboard(self) -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(EXTRA_KEYBOARD, resize_keyboard=True, is_persistent=True)

    def _remember_quick_action(self, update: Update, action: str, prompt: str) -> None:
        if not update.effective_user:
            return
        self._pending_quick_actions[update.effective_user.id] = {
            "action": action,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }

    async def _prompt_quick_action(self, update: Update, action: str, prompt: str) -> None:
        self._remember_quick_action(update, action, prompt)
        await self._reply_text(update, prompt)

    async def _handle_quick_button(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        text: str,
    ) -> bool:
        if text == MENU_BUTTON:
            self._pending_quick_actions.pop(update.effective_user.id, None) if update.effective_user else None
            await self._reply_text(update, "Основні швидкі дії:", reply_markup=self._main_keyboard())
            return True

        if text == HELP_BUTTON:
            await self.help(update, context)
            return True

        if text == EXTRA_BUTTON:
            await self._reply_text(update, "Додаткові швидкі дії:", reply_markup=self._extra_keyboard())
            return True

        if text == LINK_BUTTON:
            await self._prompt_quick_action(
                update,
                "link",
                "Надішли секретний ключ прив'язки акаунта одним повідомленням.",
            )
            return True

        if text == UNLINK_BUTTON:
            await self.unlink(update, context)
            return True

        if text == HEALTH_BUTTON:
            await self.health(update, context)
            return True

        if text == WEBAPP_BUTTON:
            await self.webapp(update, context)
            return True

        if text == DASHBOARD_BUTTON:
            await self.dashboard(update, context)
            return True

        if text == STATISTICS_BUTTON:
            await self._prompt_quick_action(
                update,
                "statistics",
                "За скільки місяців показати статистику? Наприклад: 6. Напиши 0 або '-' для стандартного періоду.",
            )
            return True

        if text == CATEGORIES_BUTTON:
            await self.categories(update, context)
            return True

        if text == CALENDAR_BUTTON:
            await self._prompt_quick_action(
                update,
                "calendar",
                "Введи рік і місяць через пробіл, наприклад: 2026 5. Напиши '-' для поточного календаря.",
            )
            return True

        if text == DAY_BUTTON:
            await self._prompt_quick_action(
                update,
                "day",
                "Введи дату у форматі YYYY MM DD, наприклад: 2026 5 21.",
            )
            return True

        if text == TRANSACTIONS_BUTTON:
            await self._prompt_quick_action(
                update,
                "transactions",
                "Введи фільтри key=value або '-' щоб показати список без фільтрів.",
            )
            return True

        if text == TRANSACTION_DETAIL_BUTTON:
            await self._prompt_quick_action(update, "transaction_detail", "Введи ID транзакції.")
            return True

        if text == CREATE_TRANSACTION_BUTTON:
            await self._prompt_quick_action(
                update,
                "create_transaction",
                (
                    "Введи дані транзакції у форматі key=value або JSON.\n"
                    "Приклад: amount=250 category_name=продукти description=АТБ transaction_date=2026-05-21"
                ),
            )
            return True

        if text == UPDATE_TRANSACTION_BUTTON:
            await self._prompt_quick_action(
                update,
                "update_transaction",
                "Введи ID і поля для оновлення. Приклад: 12 amount=300 category_name=транспорт",
            )
            return True

        if text == DELETE_TRANSACTION_BUTTON:
            await self._prompt_quick_action(update, "delete_transaction", "Введи ID транзакції для видалення.")
            return True

        if text == BUDGETS_BUTTON:
            await self._prompt_quick_action(
                update,
                "budgets",
                "Введи month=YYYY-MM-01 або '-' щоб показати бюджети без фільтра.",
            )
            return True

        if text == BUDGET_DETAIL_BUTTON:
            await self._prompt_quick_action(update, "budget_detail", "Введи ID бюджету.")
            return True

        if text == CREATE_BUDGET_BUTTON:
            await self._prompt_quick_action(
                update,
                "create_budget",
                "Введи бюджет у форматі key=value або JSON. Приклад: category_name=їжа amount=5000 month=2026-05-01",
            )
            return True

        if text == UPDATE_BUDGET_BUTTON:
            await self._prompt_quick_action(
                update,
                "update_budget",
                "Введи ID і поля для оновлення. Приклад: 3 amount=6500",
            )
            return True

        if text == DELETE_BUDGET_BUTTON:
            await self._prompt_quick_action(update, "delete_budget", "Введи ID бюджету для видалення.")
            return True

        return False

    async def _try_handle_quick_action_reply(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        text: str,
    ) -> bool:
        if not update.effective_user:
            return False

        pending = self._pending_quick_actions.get(update.effective_user.id)
        if not pending:
            return False

        action = pending.get("action")
        payload_text = text.strip()
        if payload_text.lower() in {"cancel", "скасувати"}:
            self._pending_quick_actions.pop(update.effective_user.id, None)
            await self._reply_text(update, "Скасовано.")
            return True

        if action == "link":
            await self._link_from_secret(update, payload_text)
            self._pending_quick_actions.pop(update.effective_user.id, None)
            return True

        link = self._require_link(update)
        if not link:
            await self._reply_text(update, "Спочатку прив'яжи акаунт кнопкою прив'язки.")
            return True

        result: Optional[ApiResult] = None
        retry: Optional[Dict[str, Any]] = None

        try:
            if action == "statistics":
                params = None
                if payload_text and payload_text not in {"-", "0"}:
                    params = {"months": str(int(payload_text))}
                result = await self._call_api(update, "GET", build_telegram_path("statistics"), params=params)

            elif action == "calendar":
                params = None
                if payload_text and payload_text != "-":
                    parts = payload_text.split()
                    if len(parts) < 2:
                        raise ValueError("calendar")
                    params = {"year": str(int(parts[0])), "month": str(int(parts[1]))}
                result = await self._call_api(update, "GET", build_telegram_path("calendar"), params=params)

            elif action == "day":
                parts = payload_text.split()
                if len(parts) < 3:
                    raise ValueError("day")
                year, month, day = (int(parts[0]), int(parts[1]), int(parts[2]))
                result = await self._call_api(update, "GET", build_telegram_path(f"calendar/{year}/{month}/{day}"))

            elif action == "transactions":
                params = None if payload_text == "-" else {
                    k: str(v) for k, v in parse_kv_args(payload_text).items()
                } or None
                result = await self._call_api(update, "GET", build_telegram_path("transactions"), params=params)

            elif action == "transaction_detail":
                result = await self._call_api(
                    update,
                    "GET",
                    build_telegram_path(f"transactions/{int(payload_text)}"),
                )

            elif action == "create_transaction":
                payload = parse_payload(payload_text)
                path = build_telegram_path("transactions")
                result = await self._call_api(update, "POST", path, json=payload)
                retry = {"action": action, "method": "POST", "path": path, "json": payload}

            elif action == "update_transaction":
                item_id, payload = self._split_id_and_payload(payload_text)
                path = build_telegram_path(f"transactions/{item_id}")
                result = await self._call_api(update, "PATCH", path, json=payload)
                retry = {"action": action, "method": "PATCH", "path": path, "json": payload}

            elif action == "delete_transaction":
                result = await self._call_api(
                    update,
                    "DELETE",
                    build_telegram_path(f"transactions/{int(payload_text)}"),
                )

            elif action == "budgets":
                params = None if payload_text == "-" else {
                    k: str(v) for k, v in parse_kv_args(payload_text).items()
                } or None
                result = await self._call_api(update, "GET", build_telegram_path("budgets"), params=params)

            elif action == "budget_detail":
                result = await self._call_api(update, "GET", build_telegram_path(f"budgets/{int(payload_text)}"))

            elif action == "create_budget":
                payload = parse_payload(payload_text)
                path = build_telegram_path("budgets")
                result = await self._call_api(update, "POST", path, json=payload)
                retry = {"action": action, "method": "POST", "path": path, "json": payload}

            elif action == "update_budget":
                item_id, payload = self._split_id_and_payload(payload_text)
                path = build_telegram_path(f"budgets/{item_id}")
                result = await self._call_api(update, "PATCH", path, json=payload)
                retry = {"action": action, "method": "PATCH", "path": path, "json": payload}

            elif action == "delete_budget":
                result = await self._call_api(update, "DELETE", build_telegram_path(f"budgets/{int(payload_text)}"))

            else:
                return False
        except (TypeError, ValueError):
            await self._reply_text(update, "Не вдалося розібрати параметри. Натисни кнопку ще раз і введи приклад з підказки.")
            return True

        self._pending_quick_actions.pop(update.effective_user.id, None)
        if result is not None:
            await self._reply_result(update, result, retry=retry)
        return True

    def _split_id_and_payload(self, text: str) -> tuple[int, Dict[str, Any]]:
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            raise ValueError("Expected ID and payload")
        return int(parts[0]), parse_payload(parts[1])

    async def _link_from_secret(self, update: Update, secret: str) -> None:
        if not update.message or not update.effective_user:
            return
        if not secret:
            await self._reply_text(update, "Надішли секретний ключ прив'язки.")
            return

        access_token, refresh_token, error = await self._resolve_secret(
            secret,
            update.effective_user.id,
            update.effective_user.username,
        )
        if error:
            await self._reply_text(update, error)
            return

        health = await self._client.request(
            "GET",
            build_telegram_path("health"),
            access_token=access_token,
            headers=self._telegram_headers(update.effective_user.id),
        )
        if health.status_code != 200:
            await self._reply_text(update, "Прив'язка не вдалася. Секретний ключ недійсний або застарів.")
            return

        account = LinkedAccount(
            telegram_user_id=update.effective_user.id,
            telegram_username=update.effective_user.username,
            access_token=access_token,
            refresh_token=refresh_token,
            linked_at=self._store.now_iso(),
        )
        self._store.save(account)
        await self._reply_text(update, "Акаунт успішно прив'язано.")

    def _build_webapp_url(self, access_token: str) -> str:
        base = self._config.webapp_url or ""
        parts = urlsplit(base)
        path = parts.path.rstrip("/")
        if not path.endswith("/telegram-webapp"):
            path = f"{path}/telegram-webapp" if path else "/telegram-webapp"
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["access_token"] = access_token
        return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), parts.fragment))

    async def upload_document(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        # Завантажує PDF/CSV/XLS/XLSX-виписки через /api/telegram/uploads/.

        if not update.message or not update.message.document or not update.effective_user:
            return

        link = self._store.get(update.effective_user.id)
        if not link:
            await self._reply_text(update, "Спочатку прив'яжи акаунт кнопкою прив'язки.")
            return

        file_name = update.message.document.file_name or ""
        suffix = Path(file_name).suffix.lower()
        if suffix not in {".pdf", ".csv", ".xls", ".xlsx"}:
            await update.message.reply_text("Only PDF/CSV/XLS/XLSX files are supported.")
            return

        args = parse_kv_args(update.message.caption or "")
        bank = args.get("bank")
        bank_name = args.get("bank_name")
        if not bank and not bank_name:
            await update.message.reply_text("Caption must include bank=ID or bank_name=NAME.")
            return

        telegram_file = await context.bot.get_file(update.message.document.file_id)
        with TemporaryDirectory() as tmp_dir:
            local_path = Path(tmp_dir) / file_name
            await telegram_file.download_to_drive(custom_path=str(local_path))

            result = await self._upload_statement(link, local_path, bank, bank_name)
            await self._reply_result(update, result)

    async def _upload_statement(
        self,
        link: LinkedAccount,
        local_path: Path,
        bank: Optional[Any],
        bank_name: Optional[Any],
    ) -> ApiResult:
        data: Dict[str, str] = {}
        if bank is not None:
            data["bank"] = str(bank)
        if bank_name is not None:
            data["bank_name"] = str(bank_name)

        with local_path.open("rb") as handle:
            files = {"file": (local_path.name, handle, "application/octet-stream")}
            result = await self._client.request(
                "POST",
                build_telegram_path("uploads"),
                access_token=link.access_token,
                headers=self._telegram_headers(link.telegram_user_id),
                data=data,
                files=files,
            )

        if result.status_code == 401 and link.refresh_token:
            new_access = await self._client.refresh_access(link.refresh_token)
            if not new_access:
                return result
            self._store.update_tokens(link.telegram_user_id, new_access, link.refresh_token)

            with local_path.open("rb") as handle:
                files = {"file": (local_path.name, handle, "application/octet-stream")}
                return await self._client.request(
                    "POST",
                    build_telegram_path("uploads"),
                    access_token=new_access,
                    headers=self._telegram_headers(link.telegram_user_id),
                    data=data,
                    files=files,
                )

        return result

    async def _call_api(
        self,
        update: Update,
        method: str,
        path: str,
        params: Optional[Dict[str, str]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> ApiResult:
        link = self._require_link(update)
        if not link:
            return ApiResult(status_code=401, data="Not linked", error="Not linked")

        result = await self._client.request(
            method,
            path,
            access_token=link.access_token,
            headers=self._telegram_headers(link.telegram_user_id),
            params=params,
            json=json,
        )

        if result.status_code == 401 and link.refresh_token:
            new_access = await self._client.refresh_access(link.refresh_token)
            if not new_access:
                return result
            self._store.update_tokens(link.telegram_user_id, new_access, link.refresh_token)
            result = await self._client.request(
                method,
                path,
                access_token=new_access,
                headers=self._telegram_headers(link.telegram_user_id),
                params=params,
                json=json,
            )

        if result.status_code == 403:
            self._store.remove(link.telegram_user_id)
            return ApiResult(
                status_code=403,
                data=(
                    "Telegram прив'язку для цього профілю видалено. "
                    "Натисни кнопку прив'язки в боті й введи новий ключ із профілю."
                ),
                error="Telegram link revoked",
            )

        return result

    @staticmethod
    def _telegram_headers(telegram_user_id: int) -> Dict[str, str]:
        return {"X-Telegram-User-Id": str(telegram_user_id)}

    async def _resolve_secret(
        self,
        secret: str,
        telegram_user_id: int,
        telegram_username: Optional[str],
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        if self._config.link_endpoint:
            endpoint = self._config.link_endpoint
            if not endpoint.endswith('/'):
                endpoint = f"{endpoint}/"
            result = await self._client.request(
                "POST",
                endpoint,
                json={
                    "secret": secret,
                    "telegram_user_id": telegram_user_id,
                    "telegram_username": telegram_username,
                },
            )
            if result.status_code >= 400:
                return None, None, f"Link endpoint failed ({result.status_code})."
            if not isinstance(result.data, dict):
                return None, None, "Link endpoint returned invalid response."

            access_token = result.data.get("access") or result.data.get("token")
            refresh_token = result.data.get("refresh")
            if not access_token:
                return None, None, "Link endpoint response missing access token."
            return str(access_token), str(refresh_token) if refresh_token else None, None

        return secret, None, None

    def _require_link(self, update: Update) -> Optional[LinkedAccount]:
        if not update.message or not update.effective_user:
            return None
        link = self._store.get(update.effective_user.id)
        if not link:
            return None
        return link

    def _get_args_text(self, update: Update) -> str:
        if not update.message or not update.message.text:
            return ""
        parts = update.message.text.split(maxsplit=1)
        return parts[1] if len(parts) > 1 else ""

    async def _reply_result(
        self,
        update: Update,
        result: ApiResult,
        retry: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not update.message:
            return
        if result.error and retry:
            missing_category = self._remember_retry_if_category_missing(update, result, retry)
            if missing_category:
                await self._send_category_retry_prompt(update, missing_category)
                return
        if result.error:
            message = f"Request failed ({result.status_code}).\n{format_response(result.data)}"
        elif result.status_code == 204 or result.data == "":
            message = "Готово."
        else:
            message = format_response(result.data)
        await update.message.reply_text(message, reply_markup=self._main_keyboard())

    async def _reply_text(
        self,
        update: Update,
        message: str,
        reply_markup: Optional[ReplyKeyboardMarkup] = None,
    ) -> None:
        if update.message:
            await update.message.reply_text(message, reply_markup=reply_markup or self._main_keyboard())

    def _log_expense(self, update: Update, payload: Dict[str, Any], status_code: int) -> None:
        # Додає однорядковий запис у лог створення витрати.
        try:
            log_path = self._log_dir / "expenses.log"
            user_id = update.effective_user.id if update.effective_user else "unknown"
            timestamp = datetime.datetime.utcnow().isoformat()
            amount = payload.get("amount")
            category = payload.get("category_name", "")
            date_value = payload.get("transaction_date") or payload.get("date", "")
            line = (
                f"{timestamp} user_id={user_id} amount={amount} "
                f"category={category} date={date_value} status={status_code}\n"
            )
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except Exception:
            return

    def _extract_missing_category(self, data: Any) -> Optional[str]:
        if not isinstance(data, dict):
            return None
        raw = data.get("category_name")
        if isinstance(raw, list):
            raw_text = " ".join(str(item) for item in raw)
        elif raw:
            raw_text = str(raw)
        else:
            return None

        match = re.search(r'Category "([^"]+)" was not found', raw_text)
        if match:
            return match.group(1)
        if "was not found" in raw_text or "not found" in raw_text:
            return raw_text
        return None

    def _remember_retry_if_category_missing(
        self,
        update: Update,
        result: ApiResult,
        retry: Dict[str, Any],
    ) -> Optional[str]:
        if not update.effective_user:
            return None
        missing_category = self._extract_missing_category(result.data)
        if not missing_category:
            return None

        self._pending_clarifications[update.effective_user.id] = {
            "kind": "retry_payload",
            "retry": retry,
            "missing_category": missing_category,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }
        return missing_category

    async def _send_category_retry_prompt(
        self,
        update: Update,
        missing_category: str,
    ) -> None:
        await self._reply_text(
            update,
            (
                f"Не знайшов категорію \"{missing_category}\". "
                "Напиши наступним повідомленням правильну категорію, наприклад: їжа, продукти, транспорт."
            ),
        )

    def _clean_category_reply(self, text: str) -> str:
        cleaned = (text or "").strip()
        for _ in range(2):
            cleaned = re.sub(
                r"^[\s,.;:!?]*(це|категорія|категорію|в категорію|до категорії)\s+",
                "",
                cleaned,
                flags=re.I,
            )
        cleaned = re.sub(r"[\s,.;:!?]+$", "", cleaned)
        return cleaned.strip() or text.strip()

    async def _try_handle_pending_reply(self, update: Update, text: str) -> bool:
        if not update.effective_user:
            return False
        pending = self._pending_clarifications.get(update.effective_user.id)
        if not pending or pending.get("kind") != "retry_payload":
            return False

        retry = pending.get("retry") or {}
        payload = dict(retry.get("json") or {})
        payload["category_name"] = self._clean_category_reply(text)
        result = await self._call_api(
            update,
            retry.get("method", "POST"),
            retry.get("path", build_telegram_path("transactions")),
            json=payload,
        )

        if not result.error:
            self._pending_clarifications.pop(update.effective_user.id, None)

        retry_next = {**retry, "json": payload}
        await self._reply_result(update, result, retry=retry_next)
        return True


    async def voice_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        # Обробляє voice-повідомлення через AI-пайплайн.
        if not update.message or not update.message.voice or not update.effective_user:
            return

        link = self._require_link(update)
        if not link:
            await self._reply_text(update, "⚠️ Спочатку прив'яжи акаунт кнопкою прив'язки.")
            return

        await self._reply_text(update, "🎤 Обробляю голосове повідомлення...")

        voice_file = await context.bot.get_file(update.message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await voice_file.download_to_drive(tmp.name)
            audio_path = tmp.name

        try:
            text = self._ai.transcribe(audio_path)
            await self._reply_text(update, f"🗣 «{text}»")
            if await self._try_handle_pending_reply(update, text):
                return
            pending = self._pending_clarifications.get(update.effective_user.id)
            context_text = None
            if pending:
                context_text = (
                    f"Попередній запит: {pending.get('raw_text', '')}\n"
                    f"Попередній intent: {pending.get('intent', {})}\n"
                    f"Уточнення користувача: {text}"
                )
            intent = await self._ai.parse_intent(text, context=context_text)
            await self._dispatch_intent(update, intent, raw_text=text)
        except Exception as exc:
            await self._reply_text(update, f"❌ Помилка: {exc}")
        finally:
            os.unlink(audio_path)

    async def text_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        # Обробляє звичайний текст як команду для асистента.
        if not update.message or not update.message.text or not update.effective_user:
            return

        text = update.message.text.strip()
        if not text:
            return

        if await self._handle_quick_button(update, context, text):
            return

        if await self._try_handle_quick_action_reply(update, context, text):
            return

        link = self._require_link(update)
        if not link:
            await self._reply_text(update, "Спочатку прив'яжи акаунт кнопкою прив'язки.")
            return

        if await self._try_handle_pending_reply(update, text):
            return

        pending = self._pending_clarifications.get(update.effective_user.id)
        context_text = None
        if pending:
            context_text = (
                f"Попередній запит: {pending.get('raw_text', '')}\n"
                f"Попередній intent: {pending.get('intent', {})}\n"
                f"Уточнення користувача: {text}"
            )

        try:
            intent = await self._ai.parse_intent(text, context=context_text)
            await self._dispatch_intent(update, intent, raw_text=text)
        except Exception as exc:
            await self._reply_text(update, f"Не зміг розібрати повідомлення: {exc}")



    async def _dispatch_intent(
        self,
        update: Update,
        intent: dict,
        raw_text: Optional[str] = None,
    ) -> None:
        # Зіставляє AI intent з викликом backend API.
        action = intent.get("action", "unknown")
        user_id = update.effective_user.id if update.effective_user else None

        if action == "ask_clarification":
            if user_id is not None:
                self._pending_clarifications[user_id] = {
                    "intent": intent,
                    "raw_text": raw_text or "",
                    "created_at": datetime.datetime.utcnow().isoformat(),
                }
            msg = intent.get("message", "Уточни, будь ласка, деталі запиту.")
            await self._reply_text(update, f"Потрібне уточнення: {msg}")
            return

        pending_before_dispatch = (
            self._pending_clarifications.get(user_id) if user_id is not None else None
        )
        original_raw_text = (
            pending_before_dispatch.get("raw_text")
            if isinstance(pending_before_dispatch, dict)
            and pending_before_dispatch.get("kind") != "retry_payload"
            and pending_before_dispatch.get("raw_text")
            else raw_text
        )

        if user_id is not None:
            self._pending_clarifications.pop(user_id, None)

        if action == "create_transaction":
            description = clean_transaction_description(
                intent.get("description"),
                original_raw_text,
            )
            if not description:
                description = "Voice transaction"
            category_name = resolve_spoken_category(
                intent.get("category_name", ""),
                original_raw_text,
            )
            date_value = (
                intent.get("transaction_date")
                or intent.get("date")
                or datetime.date.today().isoformat()
            )
            payload = {
                "amount":        intent.get("amount"),
                "category_name": category_name,
                "description":   description,
                "transaction_date": date_value,
            }
            path = build_telegram_path("transactions")
            result = await self._call_api(
                update, "POST", path, json=payload
            )
            self._log_expense(update, payload, result.status_code)
            retry = {
                "action": "create_transaction",
                "method": "POST",
                "path": path,
                "json": payload,
            }

        elif action == "get_dashboard":
            result = await self._call_api(update, "GET", build_telegram_path("dashboard"))
            retry = None

        elif action == "get_statistics":
            params = {}
            if intent.get("months"):
                params["months"] = str(intent.get("months"))
            result = await self._call_api(
                update,
                "GET",
                build_telegram_path("statistics"),
                params=params or None,
            )
            retry = None

        elif action == "get_categories":
            result = await self._call_api(update, "GET", build_telegram_path("categories"))
            retry = None

        elif action == "get_calendar":
            params = {}
            if intent.get("year"):
                params["year"] = str(intent.get("year"))
            if intent.get("month"):
                params["month"] = str(intent.get("month"))
            result = await self._call_api(
                update,
                "GET",
                build_telegram_path("calendar"),
                params=params or None,
            )
            retry = None

        elif action == "get_day":
            year = intent.get("year")
            month = intent.get("month")
            day = intent.get("day")
            if not all([year, month, day]):
                await self._reply_text(update, "Потрібне уточнення: за яку дату показати транзакції?")
                return
            result = await self._call_api(
                update,
                "GET",
                build_telegram_path(f"calendar/{year}/{month}/{day}"),
            )
            retry = None

        elif action == "get_transactions":
            filters = {k: str(v) for k, v in intent.get("filters", {}).items()}
            result = await self._call_api(
                update, "GET", build_telegram_path("transactions"),
                params=filters or None,
            )
            retry = None

        elif action == "get_transaction_detail":
            tid = intent.get("id")
            if not tid:
                await self._reply_text(update, "Потрібне уточнення: яку транзакцію показати?")
                return
            result = await self._call_api(
                update, "GET", build_telegram_path(f"transactions/{tid}")
            )
            retry = None

        elif action == "create_budget":
            payload = {
                "category_name": intent.get("category_name"),
                "amount":        intent.get("amount") or intent.get("limit"),
                "month":         intent.get("month"),
            }
            path = build_telegram_path("budgets")
            result = await self._call_api(
                update, "POST", path, json=payload
            )
            retry = {
                "action": "create_budget",
                "method": "POST",
                "path": path,
                "json": payload,
            }

        elif action == "get_budgets":
            params = {"month": intent["month"]} if "month" in intent else None
            result = await self._call_api(
                update, "GET", build_telegram_path("budgets"), params=params,
            )
            retry = None

        elif action == "update_budget":
            bid = intent.get("id")
            if not bid:
                await self._reply_text(update, "Потрібне уточнення: який бюджет оновити?")
                return
            fields = dict(intent.get("fields") or {})
            if "limit" in fields and "amount" not in fields:
                fields["amount"] = fields.pop("limit")
            result = await self._call_api(
                update, "PATCH", build_telegram_path(f"budgets/{bid}"), json=fields
            )
            retry = {
                "action": "update_budget",
                "method": "PATCH",
                "path": build_telegram_path(f"budgets/{bid}"),
                "json": fields,
            }

        elif action == "delete_budget":
            bid = intent.get("id")
            if not bid:
                await self._reply_text(update, "Потрібне уточнення: який бюджет видалити?")
                return
            result = await self._call_api(
                update, "DELETE", build_telegram_path(f"budgets/{bid}")
            )
            retry = None

        elif action == "delete_transaction":
            tid = intent.get("id")
            result = await self._call_api(
                update, "DELETE", build_telegram_path(f"transactions/{tid}")
            )
            retry = None

        elif action == "update_transaction":
            tid = intent.get("id")
            fields = dict(intent.get("fields", {}))
            if "date" in fields and "transaction_date" not in fields:
                fields["transaction_date"] = fields.pop("date")
            result = await self._call_api(
                update, "PATCH", build_telegram_path(f"transactions/{tid}"),
                json=fields,
            )
            retry = {
                "action": "update_transaction",
                "method": "PATCH",
                "path": build_telegram_path(f"transactions/{tid}"),
                "json": fields,
            }

        elif action == "get_health":
            result = await self._call_api(update, "GET", build_telegram_path("health"))
            retry = None

        elif action == "assistant_help":
            await self._reply_text(
                update,
                intent.get("message")
                or (
                    "Можу вести облік через чат: додавати витрати й доходи, "
                    "показувати транзакції, статистику, бюджети, календар і уточнювати деталі."
                ),
            )
            return

        else:
            msg = intent.get("message", "Не вдалось розпізнати. Спробуй ще раз.")
            await self._reply_text(update, f"❓ {msg}")
            return

        await self._reply_result(update, result, retry=retry)


def register_handlers(application: Any, services: BotServices) -> None:
    # Реєструє command- і document-handler-и.

    application.add_handler(CommandHandler("start", services.start))
    application.add_handler(CommandHandler("help", services.help))
    application.add_handler(CommandHandler("link", services.link))
    application.add_handler(CommandHandler("unlink", services.unlink))
    application.add_handler(CommandHandler("health", services.health))
    application.add_handler(CommandHandler("dashboard", services.dashboard))
    application.add_handler(CommandHandler("statistics", services.statistics))
    application.add_handler(CommandHandler("categories", services.categories))
    application.add_handler(CommandHandler("calendar", services.calendar))
    application.add_handler(CommandHandler("day", services.calendar_day))
    application.add_handler(CommandHandler("transactions", services.transactions))
    application.add_handler(CommandHandler("transaction", services.transaction_detail))
    application.add_handler(CommandHandler("create_transaction", services.transaction_create))
    application.add_handler(CommandHandler("update_transaction", services.transaction_update))
    application.add_handler(CommandHandler("delete_transaction", services.transaction_delete))
    application.add_handler(CommandHandler("budgets", services.budgets))
    application.add_handler(CommandHandler("budget", services.budget_detail))
    application.add_handler(CommandHandler("create_budget", services.budget_create))
    application.add_handler(CommandHandler("update_budget", services.budget_update))
    application.add_handler(CommandHandler("delete_budget", services.budget_delete))
    application.add_handler(CommandHandler("webapp", services.webapp))
    application.add_handler(MessageHandler(filters.Document.ALL, services.upload_document))
    application.add_handler(MessageHandler(filters.VOICE, services.voice_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, services.text_message))
