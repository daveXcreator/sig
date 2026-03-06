import unittest

from app.event_classifier import classify_event_type, direction_hint_for_pair, score_event_impact
from app.schemas import SchemaValidationError


class EventClassifierTests(unittest.TestCase):
    def test_classify_event_type_rate_decision(self):
        text = "The central bank signaled a hawkish path after an interest rate hike."
        self.assertEqual("rate_decision", classify_event_type(text))

    def test_classify_event_type_inflation(self):
        text = "CPI inflation surprised to the upside this month."
        self.assertEqual("inflation", classify_event_type(text))

    def test_classify_event_type_employment(self):
        text = "Nonfarm payroll and unemployment data beat expectations."
        self.assertEqual("employment", classify_event_type(text))

    def test_classify_event_type_geopolitical(self):
        text = "Markets reacted to new sanctions and escalating conflict."
        self.assertEqual("geopolitical", classify_event_type(text))

    def test_classify_event_type_geopolitical_bombing_term(self):
        text = "FX markets reacted as reports of bombing and airstrike risk escalated."
        self.assertEqual("geopolitical", classify_event_type(text))

    def test_classify_event_type_risk_sentiment(self):
        text = "Flight to safety emerged during a broad equity selloff."
        self.assertEqual("risk_sentiment", classify_event_type(text))

    def test_classify_event_type_rate_decision_from_fed_term(self):
        text = "Fed officials signaled policy tightening may continue if inflation persists."
        self.assertEqual("rate_decision", classify_event_type(text))

    def test_classify_event_type_other(self):
        text = "Analysts discussed seasonal portfolio rebalancing."
        self.assertEqual("other", classify_event_type(text))

    def test_score_event_impact_stays_in_valid_range(self):
        high = score_event_impact(
            event_type="rate_decision",
            text="hawkish rally strengthens dollar",
            has_explicit_pair=True,
            mention_strength=1.0,
        )
        low = score_event_impact(
            event_type="other",
            text="neutral commentary",
            has_explicit_pair=False,
            mention_strength=0.0,
        )

        self.assertGreaterEqual(high, 0.0)
        self.assertLessEqual(high, 1.0)
        self.assertGreaterEqual(low, 0.0)
        self.assertLessEqual(low, 1.0)
        self.assertGreater(high, low)

    def test_direction_hint_for_pair_uses_primary_currency_position(self):
        text = "yen weakens as risk sentiment deteriorates"
        self.assertEqual(
            "bullish",
            direction_hint_for_pair("USD/JPY", "JPY", text),
        )
        self.assertEqual(
            "bearish",
            direction_hint_for_pair("USD/JPY", "USD", text),
        )

    def test_direction_hint_rejects_bad_pair_format(self):
        with self.assertRaises(SchemaValidationError):
            direction_hint_for_pair("USDJPY", "USD", "dollar strengthens")


if __name__ == "__main__":
    unittest.main()
