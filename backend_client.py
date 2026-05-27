from dataclasses import dataclass
from typing import Any, Mapping, Optional, Dict

import httpx


@dataclass
class ApiResult:
    """Нормалізований результат відповіді API."""

    status_code: int
    data: Any
    error: Optional[str]


def build_telegram_path(suffix: str) -> str:
    # Формує шлях Telegram API з початковим і кінцевим слешем.

    clean = suffix.strip("/")
    return f"/api/telegram/{clean}/"


def build_users_path(suffix: str) -> str:
    # Формує шлях users API з початковим і кінцевим слешем.

    clean = suffix.strip("/")
    return f"/api/users/{clean}/"


def build_transactions_api_path(suffix: str) -> str:
    # Формує шлях transactions API з початковим і кінцевим слешем.

    clean = suffix.strip("/")
    return f"/transactions/api/{clean}/"


class BackendClient:
    """Обгортка HTTP-клієнта для викликів MyHaven backend."""

    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def request(
        self,
        method: str,
        path: str,
        access_token: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        params: Optional[Mapping[str, str]] = None,
        json: Any = None,
        data: Optional[Mapping[str, str]] = None,
        files: Optional[Dict[str, Any]] = None,
    ) -> ApiResult:
        request_headers: Dict[str, str] = dict(headers or {})
        if access_token:
            request_headers["Authorization"] = f"Bearer {access_token}"

        response = await self._client.request(
            method,
            path,
            headers=request_headers,
            params=params,
            json=json,
            data=data,
            files=files,
        )
        return self._to_result(response)

    async def refresh_access(self, refresh_token: str) -> Optional[str]:
        # Оновлює access token через refresh token від SimpleJWT.

        response = await self._client.post(
            "/api/token/refresh/",
            json={"refresh": refresh_token},
        )
        if response.status_code != 200:
            return None
        payload = response.json()
        return payload.get("access")

    async def close(self) -> None:
        # Закриває внутрішній HTTP-клієнт.

        await self._client.aclose()

    @staticmethod
    def _to_result(response: httpx.Response) -> ApiResult:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text

        error = None
        if response.status_code >= 400:
            error = f"HTTP {response.status_code}"

        return ApiResult(status_code=response.status_code, data=payload, error=error)
