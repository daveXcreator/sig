import unittest

from app.pair_detector import extract_json_array, normalize_pairs


class PairDetectorTests(unittest.TestCase):
    def test_extract_json_array_supports_plain_and_wrapped_responses(self):
        plain = '["USD/JPY", "EUR/USD"]'
        wrapped = 'Here is the result:\n```json\n["GBP/USD"]\n```'

        self.assertEqual(["USD/JPY", "EUR/USD"], extract_json_array(plain))
        self.assertEqual(["GBP/USD"], extract_json_array(wrapped))

    def test_normalize_pairs_filters_invalid_and_duplicates(self):
        values = ["usd/jpy", "EUR/USD", "EUR/USD", "NOT_A_PAIR", 123]

        result = normalize_pairs(values)

        self.assertEqual(["USD/JPY", "EUR/USD"], result)


if __name__ == "__main__":
    unittest.main()
