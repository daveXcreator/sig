import unittest
from unittest.mock import patch

from app.technical_analyzer import get_rsi, parse_pair


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class TechnicalAnalyzerTests(unittest.TestCase):
    def test_parse_pair_validates_format(self):
        self.assertEqual(("USD", "JPY"), parse_pair("USD/JPY"))
        with self.assertRaises(ValueError):
            parse_pair("USDJPY")

    @patch("app.technical_analyzer.requests.get")
    @patch("app.technical_analyzer.ALPHA_VANTAGE_KEY", "dummy")
    def test_get_rsi_maps_signal_using_thresholds(self, requests_get_mock):
        requests_get_mock.return_value = FakeResponse(
            {
                "Technical Analysis: RSI": {
                    "2026-02-27": {"RSI": "72.4"}
                }
            }
        )

        result = get_rsi("USD/JPY")

        self.assertIsNotNone(result)
        self.assertEqual("bearish", result["signal"])
        self.assertEqual("USD/JPY", result["pair"])


if __name__ == "__main__":
    unittest.main()
