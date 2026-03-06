import unittest

from main import aggregate_sentiment_by_pair


class MainTests(unittest.TestCase):
    def test_aggregate_sentiment_by_pair_selects_highest_confidence(self):
        records = [
            {"pair": "USD/JPY", "sentiment": "bullish", "confidence": 0.4},
            {"pair": "USD/JPY", "sentiment": "bearish", "confidence": 0.8},
            {"pair": "EUR/USD", "sentiment": "neutral", "confidence": "0.6"},
            {"pair": "EUR/USD", "sentiment": "invalid", "confidence": 0.9},
        ]

        result = sorted(aggregate_sentiment_by_pair(records), key=lambda x: x["pair"])

        self.assertEqual(
            [
                {"pair": "EUR/USD", "sentiment": "neutral", "confidence": 0.6},
                {"pair": "USD/JPY", "sentiment": "bearish", "confidence": 0.8},
            ],
            result,
        )


if __name__ == "__main__":
    unittest.main()
