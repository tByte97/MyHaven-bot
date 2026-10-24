from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import json
import logging
import os


logger = logging.getLogger(__name__)


@dataclass
class LinkedAccount:
    """Описує користувача Telegram, прив'язаного до токенів backend."""

    telegram_user_id: int
    telegram_username: Optional[str]
    access_token: str
    refresh_token: Optional[str]
    linked_at: str


class LinkStore:
    """Файлове сховище для токенів прив'язки Telegram."""

    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path
        self._links: Dict[str, Dict[str, Any]] = {}
        self._load()

    def get(self, telegram_user_id: int) -> Optional[LinkedAccount]:
        # Повертає прив'язаний акаунт за Telegram user id.

        raw = self._links.get(str(telegram_user_id))
        if not raw:
            return None
        return LinkedAccount(
            telegram_user_id=raw["telegram_user_id"],
            telegram_username=raw.get("telegram_username"),
            access_token=raw["access_token"],
            refresh_token=raw.get("refresh_token"),
            linked_at=raw["linked_at"],
        )

    def save(self, account: LinkedAccount) -> None:
        # Зберігає прив'язаний акаунт.

        self._links[str(account.telegram_user_id)] = {
            "telegram_user_id": account.telegram_user_id,
            "telegram_username": account.telegram_username,
            "access_token": account.access_token,
            "refresh_token": account.refresh_token,
            "linked_at": account.linked_at,
        }
        self._write()

    def update_tokens(
        self,
        telegram_user_id: int,
        access_token: str,
        refresh_token: Optional[str],
    ) -> None:
        # Оновлює access/refresh token для прив'язаного акаунта.

        raw = self._links.get(str(telegram_user_id))
        if not raw:
            return
        raw["access_token"] = access_token
        raw["refresh_token"] = refresh_token
        self._write()

    def remove(self, telegram_user_id: int) -> None:
        # Видаляє прив'язаний акаунт зі сховища.

        self._links.pop(str(telegram_user_id), None)
        self._write()

    @staticmethod
    def now_iso() -> str:
        # Повертає поточний timestamp у форматі ISO.

        return datetime.now(timezone.utc).isoformat()

    def _load(self) -> None:
        if not self._file_path.exists():
            return
        try:
            raw = json.loads(self._file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Failed to parse Telegram link store: %s", self._file_path)
            return
        if isinstance(raw, dict):
            self._links = raw

    def _write(self) -> None:
        # Файл містить JWT користувачів: доступ лише власнику процесу.
        self._file_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = json.dumps(self._links, indent=2, ensure_ascii=True)
        tmp_path = self._file_path.with_name(f"{self._file_path.name}.tmp")
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(self._file_path)
