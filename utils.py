import json
import re
import shlex
from typing import Any, Dict


def normalize_value(value: str) -> Any:
    # Нормалізує рядкове значення в bool/int/float, якщо це можливо.

    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def parse_kv_args(text: str) -> Dict[str, Any]:
    # Розбирає пари key=value з рядка аргументів команди.

    result: Dict[str, Any] = {}
    if not text:
        return result

    try:
        tokens = shlex.split(text)
    except ValueError:
        return result

    for token in tokens:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if not key:
            continue
        result[key] = normalize_value(value)

    return result


def parse_payload(text: str) -> Dict[str, Any]:
    # Розбирає JSON payload або переходить до парсингу key=value.

    if not text:
        return {}
    trimmed = text.strip()
    if trimmed.startswith("{") or trimmed.startswith("["):
        try:
            parsed = json.loads(trimmed)
            if isinstance(parsed, dict):
                return parsed
            return {"payload": parsed}
        except json.JSONDecodeError:
            return parse_kv_args(trimmed)
    return parse_kv_args(trimmed)


def _format_amount(value: Any) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    sign = "-" if amount < 0 else ""
    return f"{sign}{abs(amount):,.2f} UAH".replace(",", " ")


def _format_date(value: Any) -> str:
    if not value:
        return "без дати"
    return str(value).replace("T", " ")[:16]


def _category_name(category: Any) -> str:
    if isinstance(category, dict):
        return category.get("name") or "без категорії"
    return str(category) if category else "без категорії"


def _format_toggle(value: Any) -> str:
    return "увімкнено" if bool(value) else "вимкнено"


def _format_yes_no(value: Any) -> str:
    return "так" if bool(value) else "ні"


def _format_tracking_sources(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "не вказано"

    labels = {
        "cash": "готівка",
        "card": "картка",
        "bank": "банк",
        "wallet": "гаманець",
        "savings": "заощадження",
        "all": "усі",
    }
    return ", ".join(labels.get(str(item), str(item)) for item in value)


def _format_theme(value: Any) -> str:
    labels = {
        "light": "світла",
        "dark": "темна",
        "auto": "авто",
    }
    return labels.get(str(value), str(value) if value else "не вказано")


def _format_language(value: Any) -> str:
    labels = {
        "uk": "українська",
        "en": "англійська",
        "de": "німецька",
        "es": "іспанська",
        "pl": "польська",
    }
    return labels.get(str(value), str(value) if value else "не вказано")


def _format_telegram_status(data: Dict[str, Any]) -> str:
    username = data.get("telegram_username")
    user_id = data.get("telegram_user_id")
    if username:
        return f"@{username}"
    if user_id:
        return f"ID {user_id}"
    return "не прив'язано"


def _format_transaction(data: Dict[str, Any]) -> str:
    lines = [
        f"Транзакцію збережено #{data.get('id')}",
        f"Сума: {_format_amount(data.get('amount'))}",
        f"Категорія: {_category_name(data.get('category'))}",
        f"Дата: {_format_date(data.get('transaction_date'))}",
    ]
    if data.get("description"):
        lines.append(f"Опис: {data['description']}")
    return "\n".join(lines)


def _format_transaction_list(data: Dict[str, Any]) -> str:
    results = data.get("results") or []
    if not results:
        return "Транзакцій за цим запитом не знайшов."

    lines = [f"Знайшов транзакцій: {data.get('count', len(results))}"]
    for item in results[:10]:
        lines.append(
            f"- #{item.get('id')} | {_format_date(item.get('transaction_date'))} | "
            f"{_format_amount(item.get('amount'))} | {_category_name(item.get('category'))} | "
            f"{item.get('description') or 'без опису'}"
        )
    if len(results) > 10:
        lines.append("Показав перші 10 записів.")
    return "\n".join(lines)


def _format_dashboard(data: Dict[str, Any]) -> str:
    lines = [
        "Фінансовий підсумок",
        f"Витрати: {_format_amount(data.get('total_expenses', 0))}",
        f"Доходи: {_format_amount(data.get('total_incomes', 0))}",
        f"Баланс: {_format_amount(data.get('balance', 0))}",
    ]

    categories = data.get("expenses_by_category") or []
    if categories:
        lines.append("Топ витрат:")
        for item in categories[:5]:
            name = item.get("category__name") or item.get("name") or "без категорії"
            total = item.get("total") or item.get("amount") or 0
            lines.append(f"- {name}: {_format_amount(total)}")
    return "\n".join(lines)


def _format_budget(data: Dict[str, Any]) -> str:
    return "\n".join([
        f"Бюджет збережено #{data.get('id')}",
        f"Категорія: {data.get('category_name') or data.get('category')}",
        f"Місяць: {data.get('month')}",
        f"Ліміт: {_format_amount(data.get('amount'))}",
        f"Вже витрачено: {_format_amount(data.get('spent', 0))}",
    ])


def _format_profile(data: Dict[str, Any]) -> str:
    lines = [
        "Профіль",
        f"Username: {data.get('username') or '—'}",
        f"Email: {data.get('email') or '—'}",
        f"Ім'я: {data.get('first_name') or '—'}",
        f"Прізвище: {data.get('last_name') or '—'}",
        f"Дата реєстрації: {_format_date(data.get('date_joined'))}",
        f"2FA: {_format_toggle(data.get('totp_enabled'))}",
        f"Тема: {_format_theme(data.get('theme'))}",
        f"Мова: {_format_language(data.get('language'))}",
        f"Базова валюта: {data.get('currency') or '—'}",
        f"Валюта відображення: {data.get('display_currency') or '—'}",
        f"Джерела відстеження: {_format_tracking_sources(data.get('tracking_sources'))}",
        f"Онбординг завершено: {_format_yes_no(data.get('onboarding_completed'))}",
        f"Telegram: {_format_telegram_status(data)}",
    ]
    return "\n".join(lines)


def _format_preferences(data: Dict[str, Any]) -> str:
    return "\n".join([
        "Налаштування",
        f"Тема: {_format_theme(data.get('theme'))}",
        f"Мова: {_format_language(data.get('language'))}",
        f"Базова валюта: {data.get('currency') or '—'}",
        f"Валюта відображення: {data.get('display_currency') or '—'}",
        f"Джерела відстеження: {_format_tracking_sources(data.get('tracking_sources'))}",
        f"Онбординг завершено: {_format_yes_no(data.get('onboarding_completed'))}",
    ])


def _format_notifications(data: Dict[str, Any]) -> str:
    lines = [
        "Сповіщення",
        f"Email: {_format_toggle(data.get('email_notifications'))}",
        f"Telegram: {_format_toggle(data.get('telegram_notifications'))}",
        f"Великі витрати: {_format_toggle(data.get('notify_large_expense'))}",
        f"Перевищення бюджету: {_format_toggle(data.get('notify_budget_exceeded'))}",
        f"Щоденний звіт: {_format_toggle(data.get('notify_daily_summary'))}",
    ]
    if "telegram_user_id" in data or "telegram_username" in data:
        lines.append(f"Telegram акаунт: {_format_telegram_status(data)}")
    return "\n".join(lines)


def _format_telegram_link_code(data: Dict[str, Any]) -> str:
    return "\n".join([
        "Ключ для прив'язки Telegram",
        f"Секрет: {data.get('secret')}",
        f"Дійсний до: {_format_date(data.get('expires_at'))}",
        "Надішли цей ключ боту через кнопку прив'язки.",
    ])


def _format_banks(items: list[Any]) -> str:
    if not items:
        return "Банків не знайшов."
    lines = ["Банки:"]
    for item in items[:30]:
        if isinstance(item, dict):
            lines.append(f"- #{item.get('id')} | {item.get('name') or 'без назви'}")
    if len(items) > 30:
        lines.append("Показав перші 30 банків.")
    return "\n".join(lines)


def _format_uploads(items: list[Any]) -> str:
    if not items:
        return "Завантажених виписок поки немає."
    lines = ["Виписки:"]
    for item in items[:10]:
        if isinstance(item, dict):
            lines.append(
                f"- #{item.get('id')} | {item.get('bank_name') or 'Невідомий банк'} | "
                f"{item.get('status') or 'UNKNOWN'} | {_format_date(item.get('uploaded_at'))} | "
                f"транзакцій {item.get('total_transactions', 0)}"
            )
    if len(items) > 10:
        lines.append("Показав перші 10 виписок.")
    return "\n".join(lines)


def _format_budget_list(items: list[Any]) -> str:
    if not items:
        return "Даних за цим запитом не знайшов."
    lines = ["Бюджети:"]
    for item in items[:10]:
        if isinstance(item, dict):
            lines.append(
                f"- #{item.get('id')} | {item.get('category_name') or item.get('category')} | "
                f"{item.get('month')} | ліміт {_format_amount(item.get('amount'))} | "
                f"витрачено {_format_amount(item.get('spent', 0))}"
            )
    if len(items) > 10:
        lines.append("Показав перші 10 бюджетів.")
    return "\n".join(lines)


def _format_category_list(items: list[Any]) -> str:
    if not items:
        return "Категорій поки не знайшов."
    lines = ["Категорії:"]
    for item in items[:30]:
        if isinstance(item, dict):
            type_label = "дохід" if item.get("type") == "INCOME" else "витрата"
            lines.append(f"- #{item.get('id')} | {item.get('name')} | {type_label}")
    if len(items) > 30:
        lines.append("Показав перші 30 категорій.")
    return "\n".join(lines)


def _format_transaction_items(items: list[Any]) -> str:
    if not items:
        return "Транзакцій за цим запитом не знайшов."
    lines = ["Транзакції:"]
    for item in items[:10]:
        if isinstance(item, dict):
            lines.append(
                f"- #{item.get('id')} | {_format_date(item.get('transaction_date'))} | "
                f"{_format_amount(item.get('amount'))} | {_category_name(item.get('category'))} | "
                f"{item.get('description') or 'без опису'}"
            )
    if len(items) > 10:
        lines.append("Показав перші 10 записів.")
    return "\n".join(lines)


def _format_statistics(data: Dict[str, Any]) -> str:
    lines = [f"Статистика за {data.get('requested_months', 'кілька')} міс."]
    monthly = data.get("monthly_summary") or []
    if monthly:
        lines.append("Місяці:")
        for item in monthly[:6]:
            month = item.get("month") or item.get("transaction_date__month") or "?"
            expenses = item.get("expenses") or item.get("total_expenses") or 0
            incomes = item.get("incomes") or item.get("total_incomes") or 0
            lines.append(f"- {month}: витрати {_format_amount(expenses)}, доходи {_format_amount(incomes)}")
    categories = data.get("expense_categories") or []
    if categories:
        lines.append("Топ категорій витрат:")
        for item in categories[:5]:
            name = item.get("category__name") or item.get("name") or "без категорії"
            total = item.get("total") or item.get("amount") or 0
            lines.append(f"- {name}: {_format_amount(total)}")
    return "\n".join(lines)


def _format_calendar(data: Dict[str, Any]) -> str:
    days = data.get("days") or []
    if not days:
        return f"У календарі за {data.get('month')}.{data.get('year')} витрат не знайшов."
    lines = [f"Календар за {data.get('month')}.{data.get('year')}"]
    for item in days[:15]:
        lines.append(
            f"- {item.get('day')}: витрати {_format_amount(item.get('expenses', 0))}, "
            f"доходи {_format_amount(item.get('incomes', 0))}"
        )
    if len(days) > 15:
        lines.append("Показав перші 15 активних днів.")
    return "\n".join(lines)


def _format_error(data: Dict[str, Any]) -> str | None:
    if "detail" in data and len(data) == 1:
        return str(data.get("detail") or "")
    if "error" in data and len(data) == 1:
        return str(data.get("error") or "")

    detail = data.get("detail") or data.get("error")
    if detail:
        return str(detail)
    parts = []
    for key, value in data.items():
        if isinstance(value, list):
            parts.append(f"{key}: {', '.join(str(item) for item in value)}")
        elif isinstance(value, dict):
            parts.append(f"{key}: {json.dumps(value, ensure_ascii=False, default=str)}")
    if parts:
        return "Потрібно уточнити дані:\n" + "\n".join(f"- {part}" for part in parts)
    return None


def format_response(data: Any, max_len: int = 3500) -> str:
    # Форматує дані відповіді API для повідомлення в Telegram.

    if isinstance(data, str):
        text = data
    elif isinstance(data, list):
        first = data[0] if data else {}
        if isinstance(first, dict) and "uploaded_at" in first:
            text = _format_uploads(data)
        elif isinstance(first, dict) and {"name", "type"}.issubset(first.keys()):
            text = _format_category_list(data)
        elif isinstance(first, dict) and {"id", "name"}.issubset(first.keys()):
            text = _format_banks(data)
        elif isinstance(first, dict) and "transaction_date" in first:
            text = _format_transaction_items(data)
        else:
            text = _format_budget_list(data)
    elif isinstance(data, dict):
        if {"username", "email", "totp_enabled"}.issubset(data.keys()):
            text = _format_profile(data)
        elif {"theme", "language", "currency", "display_currency"}.issubset(data.keys()):
            text = _format_preferences(data)
        elif "email_notifications" in data or "telegram_notifications" in data:
            text = _format_notifications(data)
        elif {"secret", "expires_at"}.issubset(data.keys()):
            text = _format_telegram_link_code(data)
        elif "results" in data and "count" in data:
            text = _format_transaction_list(data)
        elif {"total_expenses", "total_incomes", "balance"}.issubset(data.keys()):
            text = _format_dashboard(data)
        elif "monthly_summary" in data:
            text = _format_statistics(data)
        elif "days" in data:
            text = _format_calendar(data)
        elif {"amount", "transaction_date"}.issubset(data.keys()):
            text = _format_transaction(data)
        elif {"amount", "month"}.issubset(data.keys()):
            text = _format_budget(data)
        else:
            text = _format_error(data) or json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
    else:
        text = json.dumps(data, indent=2, ensure_ascii=False, default=str)

    if len(text) > max_len:
        return f"{text[:max_len]}\n...truncated..."
    return text
