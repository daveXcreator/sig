import unittest
from unittest.mock import patch

import requests

from app.telegram_bot import TELEGRAM_CAPTION_MAX_CHARS, send_telegram_message, send_telegram_photo


class TelegramBotTests(unittest.TestCase):
    @patch("app.telegram_bot.TELEGRAM_TOKEN", None)
    @patch("app.telegram_bot.TELEGRAM_CHAT_ID", None)
    def test_send_telegram_message_returns_false_when_credentials_missing(self):
        self.assertFalse(send_telegram_message("hello"))

    @patch("app.telegram_bot.requests.post")
    @patch("app.telegram_bot.TELEGRAM_TOKEN", "token")
    @patch("app.telegram_bot.TELEGRAM_CHAT_ID", "chat")
    def test_send_telegram_message_success(self, requests_post_mock):
        response = requests_post_mock.return_value
        response.raise_for_status.return_value = None

        self.assertTrue(send_telegram_message("hello"))
        requests_post_mock.assert_called_once()

    @patch("app.telegram_bot.time.sleep")
    @patch("app.telegram_bot.requests.post")
    @patch("app.telegram_bot.TELEGRAM_TOKEN", "token")
    @patch("app.telegram_bot.TELEGRAM_CHAT_ID", "chat")
    def test_send_telegram_message_retries_without_parse_mode_on_400(
        self,
        requests_post_mock,
        _sleep_mock,
    ):
        bad_response = requests.Response()
        bad_response.status_code = 400
        first_error = requests.HTTPError(response=bad_response)

        ok_response = type("Resp", (), {})()
        ok_response.raise_for_status = lambda: None

        state = {"n": 0}

        def side_effect(*_args, **_kwargs):
            state["n"] += 1
            if state["n"] == 1:
                raise first_error
            return ok_response

        requests_post_mock.side_effect = side_effect

        self.assertTrue(send_telegram_message("hello"))
        self.assertEqual(2, state["n"])

    @patch("app.telegram_bot.TELEGRAM_TOKEN", None)
    @patch("app.telegram_bot.TELEGRAM_CHAT_ID", None)
    def test_send_telegram_photo_returns_false_when_credentials_missing(self):
        self.assertFalse(send_telegram_photo("https://example.com/image.jpg"))

    @patch("app.telegram_bot.requests.post")
    @patch("app.telegram_bot.TELEGRAM_TOKEN", "token")
    @patch("app.telegram_bot.TELEGRAM_CHAT_ID", "chat")
    def test_send_telegram_photo_success(self, requests_post_mock):
        response = requests_post_mock.return_value
        response.raise_for_status.return_value = None

        self.assertTrue(send_telegram_photo("https://example.com/image.jpg", caption="hello"))
        requests_post_mock.assert_called_once()

    @patch("app.telegram_bot.requests.post")
    @patch("app.telegram_bot.TELEGRAM_TOKEN", "token")
    @patch("app.telegram_bot.TELEGRAM_CHAT_ID", "chat")
    def test_send_telegram_photo_truncates_caption(self, requests_post_mock):
        response = requests_post_mock.return_value
        response.raise_for_status.return_value = None

        long_caption = "x" * (TELEGRAM_CAPTION_MAX_CHARS + 80)
        self.assertTrue(send_telegram_photo("https://example.com/image.jpg", caption=long_caption))

        sent_payload = requests_post_mock.call_args.kwargs["json"]
        self.assertLessEqual(len(sent_payload["caption"]), TELEGRAM_CAPTION_MAX_CHARS)


if __name__ == "__main__":
    unittest.main()
