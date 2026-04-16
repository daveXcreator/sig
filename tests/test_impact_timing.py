import unittest

from app.impact_timing import (
    activation_window_for_latency,
    classify_latency,
    estimate_impact_now_score,
    evaluate_impact_timing,
)


class ImpactTimingTests(unittest.TestCase):
    def test_classify_latency_thresholds(self):
        self.assertEqual("immediate", classify_latency(0.75))
        self.assertEqual("short_lag", classify_latency(0.55))
        self.assertEqual("slow_burn", classify_latency(0.47))

    def test_activation_window_mapping(self):
        self.assertEqual(("now-30m", 90), activation_window_for_latency("immediate"))
        self.assertEqual(("1-4h", 360), activation_window_for_latency("short_lag"))
        self.assertEqual(("4-24h", 1440), activation_window_for_latency("slow_burn"))

    def test_immediate_event_scores_higher_than_other(self):
        immediate = estimate_impact_now_score(
            event_type="rate_decision",
            event_impact=0.85,
            pair_relevance=0.90,
            volatility_regime="high",
            freshness=0.90,
            source_reliability=0.85,
            surprise_strength=0.80,
            urgency_text="Breaking unexpected rate hike shock",
        )
        slow = estimate_impact_now_score(
            event_type="other",
            event_impact=0.35,
            pair_relevance=0.45,
            volatility_regime="low",
            freshness=0.40,
            source_reliability=0.50,
            surprise_strength=0.0,
            urgency_text="Routine commentary",
        )
        self.assertGreater(immediate, slow)
        self.assertGreaterEqual(immediate, 0.0)
        self.assertLessEqual(immediate, 1.0)

    def test_evaluate_impact_timing_structure(self):
        timing = evaluate_impact_timing(
            event_type="inflation",
            event_impact=0.72,
            pair_relevance=0.77,
            volatility_regime="normal",
            freshness=0.80,
            source_reliability=0.70,
            surprise_strength=0.20,
            urgency_text="CPI surprise",
        )
        self.assertIn(timing.impact_latency_class, {"immediate", "short_lag", "slow_burn"})
        self.assertGreaterEqual(timing.impact_now_score, 0.0)
        self.assertLessEqual(timing.impact_now_score, 1.0)
        self.assertIn(timing.activation_window, {"now-30m", "1-4h", "4-24h"})
        self.assertGreater(timing.expires_in_minutes, 0)


if __name__ == "__main__":
    unittest.main()
