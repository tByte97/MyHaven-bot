import unittest

from telegrambot.backend_client import (
    build_telegram_path,
    build_transactions_api_path,
    build_users_path,
)


class BackendClientPathTests(unittest.TestCase):
    def test_builds_expected_api_paths(self):
        self.assertEqual(build_telegram_path('health'), '/api/telegram/health/')
        self.assertEqual(build_users_path('/auth/login/'), '/api/users/auth/login/')
        self.assertEqual(build_transactions_api_path('uploads'), '/transactions/api/uploads/')


if __name__ == '__main__':
    unittest.main()
