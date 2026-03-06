import unittest

from app.signal_generator import generate_signals


class SignalGeneratorTests(unittest.TestCase):
    def test_generate_signals_filters_by_alignment_and_confidence(self):
        sentiment_data = [
            {"pair": "USD/JPY", "sentiment": "bearish", "confidence": 0.8},
            {"pair": "EUR/JPY", "sentiment": "bullish", "confidence": 0.9},
            {"pair": "GBP/JPY", "sentiment": "bullish", "confidence": 0.6},
        ]
        rsi_data = [
            {"pair": "USD/JPY", "rsi": 72.1, "signal": "bearish"},
            {"pair": "EUR/JPY", "rsi": 25.0, "signal": "bullish"},
            {"pair": "GBP/JPY", "rsi": 35.0, "signal": "neutral"},
        ]

        results = generate_signals(sentiment_data, rsi_data)

        self.assertEqual(2, len(results))
        self.assertEqual("USD/JPY", results[0]["pair"])
        self.assertEqual("EUR/JPY", results[1]["pair"])


if __name__ == "__main__":
    unittest.main()
