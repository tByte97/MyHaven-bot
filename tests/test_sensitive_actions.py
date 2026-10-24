import datetime
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from telegrambot.handlers import DELETE_ACCOUNT_CONFIRM_TEXT
from telegrambot.security import looks_sensitive

from .helpers import TELEGRAM_USER_ID, make_services, make_update, replies


class SensitiveActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.services, self.client, self.ai = make_services()

    async def send_text(self, text):
        update = make_update(text)
        await self.services.text_message(update, MagicMock())
        return update

    def api_calls(self):
        return [(call.args[0], call.args[1], call.kwargs.get("json"))
                for call in self.client.request.await_args_list]

    async def test_llm_confirmed_delete_does_not_delete_account(self):
        update = make_update("видали мій акаунт")
        intent = {"action": "delete_account", "password": "Pass1234!", "confirmed": True}

        await self.services._dispatch_intent(update, intent, raw_text="видали мій акаунт")

        self.assertEqual(self.api_calls(), [])
        pending = self.services._pending_clarifications[TELEGRAM_USER_ID]
        self.assertEqual(pending["kind"], "secure_input")
        self.assertEqual(pending["data"], {})
        self.assertIsNotNone(self.services._store.get(TELEGRAM_USER_ID))

    async def test_delete_account_requires_exact_phrase_then_password(self):
        await self.services.delete_account_command(make_update("/delete_account"), MagicMock())

        await self.send_text("так, видаляй")
        self.assertEqual(self.api_calls(), [])

        await self.send_text(DELETE_ACCOUNT_CONFIRM_TEXT)
        self.assertEqual(self.api_calls(), [])

        password_update = await self.send_text("Pass1234!")

        password_update.message.delete.assert_awaited_once()
        self.assertEqual(
            self.api_calls(),
            [("POST", "/api/users/delete-account/", {"password": "Pass1234!"})],
        )
        self.assertIsNone(self.services._store.get(TELEGRAM_USER_ID))
        self.ai.parse_intent.assert_not_awaited()

    async def test_change_password_never_reaches_llm_and_messages_are_deleted(self):
        await self.services.change_password_command(make_update("/change_password"), MagicMock())

        old_update = await self.send_text("OldPass1!")
        new_update = await self.send_text("NewPass2!")

        old_update.message.delete.assert_awaited_once()
        new_update.message.delete.assert_awaited_once()
        self.assertEqual(
            self.api_calls(),
            [("POST", "/api/users/change-password/",
              {"old_password": "OldPass1!", "new_password": "NewPass2!"})],
        )
        self.ai.parse_intent.assert_not_awaited()
        for reply in replies(old_update) + replies(new_update):
            self.assertNotIn("OldPass1!", reply)
            self.assertNotIn("NewPass2!", reply)

    async def test_disable_totp_uses_local_password_prompt(self):
        update = make_update("вимкни 2fa")
        await self.services._dispatch_intent(update, {"action": "disable_totp", "password": "leaked"})
        await self.send_text("RealPass1!")

        self.assertEqual(
            self.api_calls(),
            [("POST", "/api/users/totp/disable/", {"password": "RealPass1!"})],
        )

    async def test_text_mentioning_password_is_not_sent_to_llm(self):
        update = await self.send_text("зміни пароль з OldPass1 на NewPass2")

        self.ai.parse_intent.assert_not_awaited()
        update.message.delete.assert_awaited_once()
        self.assertEqual(self.api_calls(), [])

    async def test_pending_quick_action_cannot_capture_password(self):
        self.services._pending_quick_actions[TELEGRAM_USER_ID] = {"action": "transaction_detail"}

        await self.services.change_password_command(make_update("/change_password"), MagicMock())

        self.assertNotIn(TELEGRAM_USER_ID, self.services._pending_quick_actions)

    async def test_expired_flow_does_not_call_api(self):
        await self.services.disable_totp_command(make_update("/disable_2fa"), MagicMock())
        pending = self.services._pending_clarifications[TELEGRAM_USER_ID]
        old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
        pending["created_at"] = old.isoformat()

        update = await self.send_text("Pass1234!")

        update.message.delete.assert_awaited_once()
        self.assertEqual(self.api_calls(), [])
        self.assertNotIn(TELEGRAM_USER_ID, self.services._pending_clarifications)

    async def test_cancel_stops_flow(self):
        await self.services.delete_account_command(make_update("/delete_account"), MagicMock())

        await self.send_text("скасувати")
        await self.send_text(DELETE_ACCOUNT_CONFIRM_TEXT)

        self.assertEqual(self.api_calls(), [])

    async def test_secure_flow_requires_linked_account(self):
        services, client, _ = make_services(linked=False)
        update = make_update("/delete_account")

        await services.delete_account_command(update, MagicMock())

        self.assertNotIn(TELEGRAM_USER_ID, services._pending_clarifications)

    async def test_voice_is_rejected_during_secure_flow(self):
        await self.services.disable_totp_command(make_update("/disable_2fa"), MagicMock())
        update = make_update(voice=MagicMock())
        context = MagicMock()
        context.bot.get_file = AsyncMock()

        await self.services.voice_message(update, context)

        context.bot.get_file.assert_not_awaited()
        self.services._ai.transcribe.assert_not_called()

    async def test_voice_transcript_with_password_is_not_echoed_or_sent_to_llm(self):
        update = make_update(voice=MagicMock(duration=5))
        context = MagicMock()
        voice_file = MagicMock()
        voice_file.download_to_drive = AsyncMock()
        context.bot.get_file = AsyncMock(return_value=voice_file)
        self.services._ai.transcribe.return_value = "мій пароль Secret123"

        await self.services.voice_message(update, context)

        self.ai.parse_intent.assert_not_awaited()
        for reply in replies(update):
            self.assertNotIn("Secret123", reply)

    async def test_registration_password_message_is_deleted(self):
        services, _, _ = make_services(linked=False)
        await services._start_registration(make_update("/register"))
        registration = services._pending_registrations[TELEGRAM_USER_ID]
        password_step = next(
            index for index in range(10)
            if services._registration_field_name(index) == "password"
        )
        registration["step_index"] = password_step
        update = make_update("Pass1234!")

        await services.text_message(update, MagicMock())

        update.message.delete.assert_awaited_once()

    async def test_link_secret_message_is_deleted(self):
        services, client, _ = make_services(linked=False)
        update = make_update("/link abc123")

        await services._link_from_secret(update, "abc123")

        update.message.delete.assert_awaited_once()


class PromptTests(unittest.TestCase):
    def test_prompt_does_not_ask_llm_for_passwords_or_confirmation(self):
        prompt = (Path(__file__).resolve().parent.parent / "prompts" / "intent_uk.txt").read_text(
            encoding="utf-8"
        )

        self.assertNotIn('"password"', prompt)
        self.assertNotIn("confirmed", prompt)
        self.assertNotIn("old_password", prompt)

    def test_looks_sensitive(self):
        self.assertTrue(looks_sensitive("Мій ПАРОЛЬ 123"))
        self.assertTrue(looks_sensitive("change password please"))
        self.assertFalse(looks_sensitive("витратив 200 на каву"))


if __name__ == "__main__":
    unittest.main()
