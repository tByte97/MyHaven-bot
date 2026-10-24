import logging
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from telegrambot.ai_processor import AIProcessor
from telegrambot.security import SlidingWindowLimiter
from telegrambot.storage import LinkStore, LinkedAccount

from .helpers import make_config, make_services, make_update, replies


class LinkStorePermissionsTests(unittest.TestCase):
    def test_links_file_is_readable_only_by_owner(self):
        path = Path(tempfile.mkdtemp()) / "data" / "links.json"
        store = LinkStore(path)

        store.save(LinkedAccount(1, "u", "access", "refresh", LinkStore.now_iso()))

        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)


class SlidingWindowLimiterTests(unittest.TestCase):
    def test_blocks_after_limit_and_recovers_after_period(self):
        now = [0.0]
        limiter = SlidingWindowLimiter(2, 60, clock=lambda: now[0])

        self.assertTrue(limiter.allow(1))
        self.assertTrue(limiter.allow(1))
        self.assertFalse(limiter.allow(1))
        self.assertTrue(limiter.allow(2))

        now[0] = 61.0
        self.assertTrue(limiter.allow(1))


class HandlerHardeningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.services, self.client, self.ai = make_services(
            config=make_config(ai_requests_per_minute=2, voice_max_seconds=30, upload_max_bytes=100),
        )

    async def test_text_requests_to_ai_are_rate_limited(self):
        for _ in range(3):
            await self.services.text_message(make_update("покажи дашборд"), MagicMock())

        self.assertEqual(self.ai.parse_intent.await_count, 2)

    async def test_internal_errors_are_not_echoed_to_user(self):
        self.ai.parse_intent.side_effect = RuntimeError("http://internal:11434 secret detail")
        update = make_update("покажи дашборд")

        with patch("telegrambot.handlers.logger.exception"):
            await self.services.text_message(update, MagicMock())

        for reply in replies(update):
            self.assertNotIn("secret detail", reply)

    async def test_too_long_voice_is_not_downloaded(self):
        voice = MagicMock(duration=31)
        context = MagicMock()
        context.bot.get_file = AsyncMock()

        await self.services.voice_message(make_update(voice=voice), context)

        context.bot.get_file.assert_not_awaited()

    async def test_transcription_runs_outside_event_loop_thread(self):
        loop_thread = threading.get_ident()
        seen = {}

        def transcribe(path):
            seen["thread"] = threading.get_ident()
            return "покажи дашборд"

        self.services._ai.transcribe.side_effect = transcribe
        voice_file = MagicMock()
        voice_file.download_to_drive = AsyncMock()
        context = MagicMock()
        context.bot.get_file = AsyncMock(return_value=voice_file)

        await self.services.voice_message(make_update(voice=MagicMock(duration=5)), context)

        self.assertNotEqual(seen["thread"], loop_thread)

    def _document_update(self, file_name, file_size=10):
        update = make_update()
        update.message.document.file_name = file_name
        update.message.document.file_size = file_size
        update.message.caption = "bank_name=Monobank"
        return update

    async def test_document_name_cannot_escape_temp_dir(self):
        update = self._document_update("../../evil.csv")
        telegram_file = MagicMock()
        telegram_file.download_to_drive = AsyncMock()
        context = MagicMock()
        context.bot.get_file = AsyncMock(return_value=telegram_file)

        with patch.object(self.services, "_upload_statement", AsyncMock(return_value=MagicMock(
            error=None, status_code=201, data={"status": "COMPLETED"},
        ))):
            await self.services.upload_document(update, context)

        target = Path(telegram_file.download_to_drive.await_args.kwargs["custom_path"])
        self.assertEqual(target.name, "evil.csv")
        self.assertNotIn("..", target.parts)

    async def test_oversized_document_is_not_downloaded(self):
        update = self._document_update("statement.csv", file_size=101)
        context = MagicMock()
        context.bot.get_file = AsyncMock()

        await self.services.upload_document(update, context)

        context.bot.get_file.assert_not_awaited()


class GeminiThreadTests(unittest.IsolatedAsyncioTestCase):
    async def test_gemini_call_does_not_block_event_loop(self):
        processor = AIProcessor.__new__(AIProcessor)
        loop_thread = threading.get_ident()
        seen = {}

        def generate_content(prompt, generation_config):
            seen["thread"] = threading.get_ident()
            return MagicMock(text='{"action": "get_dashboard"}')

        processor._gemini = MagicMock(generate_content=generate_content)

        result = await processor._gemini_parse("prompt")

        self.assertEqual(result, {"action": "get_dashboard"})
        self.assertNotEqual(seen["thread"], loop_thread)


class LoggingTests(unittest.TestCase):
    def test_httpx_request_urls_with_bot_token_are_not_logged(self):
        from telegrambot.main import _configure_logging

        with patch("logging.basicConfig"):
            _configure_logging()

        self.assertGreaterEqual(logging.getLogger("httpx").level, logging.WARNING)


if __name__ == "__main__":
    unittest.main()
