import unittest

from app.sentiment_analyzer import extract_json_array, normalize_sentiment


class SentimentAnalyzerTests(unittest.TestCase):
    def test_extract_json_array_handles_model_wrappers(self):
        content = 'Output:\n```json\n[{"pair":"USD/JPY","sentiment":"bearish","confidence":0.8}]\n```'

        result = extract_json_array(content)

        self.assertEqual(1, len(result))
        self.assertEqual("USD/JPY", result[0]["pair"])

    def test_normalize_sentiment_enforces_pairs_sentiment_and_confidence(self):
        items = [
            {"pair": "usd/jpy", "sentiment": "bearish", "confidence": "0.7"},
            {"pair": "EUR/USD", "sentiment": "neutral", "confidence": 1.2},
            {"pair": "AUD/USD", "sentiment": "bullish", "confidence": 0.8},
            {"pair": "EUR/USD", "sentiment": "invalid", "confidence": 0.9},
        ]

        result = normalize_sentiment(items, ["USD/JPY", "EUR/USD"])

        self.assertEqual(
            [
                {"pair": "EUR/USD", "sentiment": "neutral", "confidence": 1.0},
                {"pair": "USD/JPY", "sentiment": "bearish", "confidence": 0.7},
            ],
            sorted(result, key=lambda x: x["pair"]),
        )


if __name__ == "__main__":
    unittest.main()
