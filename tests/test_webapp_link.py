import unittest
from unittest.mock import MagicMock

from telegram import InlineKeyboardMarkup

from .helpers import make_services, make_update


class WebAppButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_webapp_url_does_not_contain_access_token(self):
        services, _, _ = make_services()
        update = make_update("/webapp")

        await services.webapp(update, MagicMock())

        markup = update.message.reply_text.await_args.kwargs["reply_markup"]
        url = markup.inline_keyboard[0][0].web_app.url
        self.assertEqual(url, "https://app.test/telegram-webapp")
        self.assertNotIn("access", url)
        self.assertNotIn("token", url)

    async def test_unlinked_user_gets_no_webapp_button(self):
        services, _, _ = make_services(linked=False)
        update = make_update("/webapp")

        await services.webapp(update, MagicMock())

        markups = [call.kwargs.get("reply_markup") for call in update.message.reply_text.await_args_list]
        self.assertFalse([m for m in markups if isinstance(m, InlineKeyboardMarkup)])


if __name__ == "__main__":
    unittest.main()
