"""Захист чутливих даних у чаті: паролі не потрапляють до LLM і не лишаються в історії."""

import datetime
import logging
import re
from typing import Any, Dict

from telegram import Update
from telegram.error import TelegramError


logger = logging.getLogger(__name__)

# Повідомлення з такими словами не надсилаються в LLM: користувач міг
# вписати пароль просто в текст команди.
_SENSITIVE_TEXT_RE = re.compile(r"парол|password|passwd", re.IGNORECASE)

SECURE_FLOW_TTL = datetime.timedelta(minutes=5)

SECURE_FLOW_STEPS = {
    "change_password": ("old_password", "new_password"),
    "disable_totp": ("password",),
    "delete_account": ("confirm_phrase", "password"),
}

SECRET_STEPS = {"old_password", "new_password", "password"}


def looks_sensitive(text: str) -> bool:
    return bool(_SENSITIVE_TEXT_RE.search(text or ""))


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def is_expired(pending: Dict[str, Any], ttl: datetime.timedelta = SECURE_FLOW_TTL) -> bool:
    created_at = pending.get("created_at")
    if not created_at:
        return True
    try:
        started = datetime.datetime.fromisoformat(created_at)
    except ValueError:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=datetime.timezone.utc)
    return datetime.datetime.now(datetime.timezone.utc) - started > ttl


async def delete_user_message(update: Update) -> bool:
    """Best-effort видалення повідомлення користувача з чату (паролі, ключі)."""
    if not update.message:
        return False
    try:
        await update.message.delete()
        return True
    except TelegramError:
        logger.warning("Не вдалося видалити повідомлення з чутливими даними.")
        return False
