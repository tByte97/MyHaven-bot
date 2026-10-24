import asyncio
import os
import unittest
from unittest.mock import patch

import httpx

from telegrambot.backend_client import BOT_SECRET_HEADER, BackendClient
from telegrambot.bot_config import load_config


class BackendSecretTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_backend_request_carries_bot_secret(self):
        seen = []

        def handler(request):
            seen.append(request.headers.get(BOT_SECRET_HEADER))
            return httpx.Response(200, json={"access": "new"})

        client = BackendClient("http://backend.test", bot_secret="s3cret")
        client._client._transport = httpx.MockTransport(handler)

        await client.request("POST", "/api/users/telegram/link/", json={"secret": "x"})
        await client.refresh_access("refresh")
        await client.close()

        self.assertEqual(seen, ["s3cret", "s3cret"])


class ConfigTests(unittest.TestCase):
    def test_bot_refuses_to_start_without_backend_secret(self):
        env = {"TELEGRAM_BOT_TOKEN": "t", "MYHAVEN_BOT_API_SECRET": ""}
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ValueError):
                load_config()

    def test_secret_is_loaded_from_env(self):
        env = {"TELEGRAM_BOT_TOKEN": "t", "MYHAVEN_BOT_API_SECRET": " s3cret "}
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(load_config().backend_bot_secret, "s3cret")


if __name__ == "__main__":
    unittest.main()
