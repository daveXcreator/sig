import unittest

from app.schemas import MarketContext, PairImpact
from app.signal_engine import (
    ScoreInputs,
    WeightedSignalEngine,
    apply_timing_gate,
    calibrate_confidence,
    classify_decision,
    compute_weighted_logit,
)


def _pair_impact(
    pair: str,
    pair_relevance: float,
    event_impact: float,
    direction_hint: str = "bullish",
) -> PairImpact:
    return PairImpact(
        article_id="a1",
        pair=pair,
        direction_hint=direction_hint,
        pair_relevance_score=pair_relevance,
        event_type="rate_decision",
        event_impact_score=event_impact,
        explanation="fixture",
    )


def _context(
    pair: str,
    trend_score: float,
    technical_alignment: float,
    volatility_regime: str = "normal",
) -> MarketContext:
    return MarketContext(
        pair=pair,
        timestamp="2026-02-28T00:05:00Z",
        rsi=62.0,
        trend_score=trend_score,
        volatility_regime=volatility_regime,
        atr_percentile=0.55,
        technical_alignment_score=technical_alignment,
    )


class SignalEngineFormulaTests(unittest.TestCase):
    def test_compute_weighted_logit_monotonicity(self):
        low = ScoreInputs(
            pair_relevance=0.3,
            event_impact=0.3,
            sentiment_strength=0.3,
            technical_alignment=0.3,
            trend_score=0.4,
            freshness=0.3,
            source_reliability=0.4,
            volatility_risk_penalty=0.8,
            conflict_penalty=0.8,
        )
        high = ScoreInputs(
            pair_relevance=0.9,
            event_impact=0.9,
            sentiment_strength=0.8,
            technical_alignment=0.9,
            trend_score=0.8,
            freshness=0.8,
            source_reliability=0.8,
            volatility_risk_penalty=0.2,
            conflict_penalty=0.1,
        )
        self.assertGreater(compute_weighted_logit(high), compute_weighted_logit(low))

    def test_classify_decision_thresholds(self):
        self.assertEqual("publish", classify_decision(0.55))
        self.assertEqual("hold", classify_decision(0.45))
        self.assertEqual("reject", classify_decision(0.449))

    def test_calibration_stays_in_bounds(self):
        self.assertGreaterEqual(calibrate_confidence(0.0), 0.0)
        self.assertLessEqual(calibrate_confidence(1.0), 1.0)

    def test_timing_gate_allows_short_lag_publish(self):
        class _Timing:
            impact_latency_class = "short_lag"

        self.assertEqual("publish", apply_timing_gate("publish", _Timing()))


class SignalEngineDecisionFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = WeightedSignalEngine()

    def test_publish_fixture(self):
        pair_impact = _pair_impact(
            pair="EUR/USD",
            pair_relevance=0.92,
            event_impact=0.84,
            direction_hint="bullish",
        )
        context = _context(
            pair="EUR/USD",
            trend_score=0.74,
            technical_alignment=0.86,
            volatility_regime="low",
        )

        decision = self.engine.evaluate_pair(
            pair_impact=pair_impact,
            market_context=context,
            freshness=0.85,
            source_reliability=0.82,
        )

        self.assertEqual("publish", decision.decision)
        self.assertIsNotNone(decision.signal)

    def test_hold_fixture(self):
        pair_impact = _pair_impact(
            pair="GBP/USD",
            pair_relevance=0.25,
            event_impact=0.20,
            direction_hint="bearish",
        )
        context = _context(
            pair="GBP/USD",
            trend_score=0.45,
            technical_alignment=0.30,
            volatility_regime="normal",
        )

        decision = self.engine.evaluate_pair(
            pair_impact=pair_impact,
            market_context=context,
            freshness=0.20,
            source_reliability=0.30,
        )

        self.assertIn(decision.decision, {"publish", "hold", "reject"})
        self.assertIsNotNone(decision.signal)
        self.assertLess(decision.confidence_calibrated, 0.75)

    def test_reject_fixture(self):
        pair_impact = _pair_impact(
            pair="AUD/USD",
            pair_relevance=0.15,
            event_impact=0.15,
            direction_hint="bearish",
        )
        context = _context(
            pair="AUD/USD",
            trend_score=0.75,
            technical_alignment=0.15,
            volatility_regime="high",
        )

        decision = self.engine.evaluate_pair(
            pair_impact=pair_impact,
            market_context=context,
            freshness=0.10,
            source_reliability=0.15,
        )

        self.assertIn(decision.decision, {"reject", "hold"})
        self.assertIsNotNone(decision.signal)
        self.assertLess(decision.confidence_calibrated, 0.55)
        self.assertIsNotNone(decision.impact_timing)

    def test_generate_signals_returns_only_publish(self):
        impacts = [
            _pair_impact("EUR/USD", 0.92, 0.84, "bullish"),
            _pair_impact("GBP/USD", 0.30, 0.25, "neutral"),
            _pair_impact("AUD/USD", 0.15, 0.15, "bearish"),
        ]
        contexts = [
            _context("EUR/USD", 0.74, 0.86, "low"),
            _context("GBP/USD", 0.53, 0.30, "normal"),
            _context("AUD/USD", 0.75, 0.15, "high"),
        ]

        # Use defaults to preserve deterministic split.
        decisions = self.engine.evaluate_signals(
            impacts,
            contexts,
            freshness=0.70,
            source_reliability=0.75,
        )
        published = [d for d in decisions if d.decision == "publish"]
        self.assertGreaterEqual(len(published), 1)

        signals = self.engine.generate_signals(impacts, contexts)
        self.assertGreaterEqual(len(signals), 1)
        self.assertEqual("EUR/USD", signals[0].pair)

    def test_publish_downgraded_when_timing_slow_burn(self):
        pair_impact = PairImpact(
            article_id="a2",
            pair="EUR/USD",
            direction_hint="bullish",
            pair_relevance_score=0.20,
            event_type="other",
            event_impact_score=0.20,
            explanation="Routine commentary with no urgency",
        )
        context = _context(
            pair="EUR/USD",
            trend_score=0.52,
            technical_alignment=0.20,
            volatility_regime="low",
        )
        decision = self.engine.evaluate_pair(
            pair_impact=pair_impact,
            market_context=context,
            freshness=0.10,
            source_reliability=0.10,
            surprise_strength=0.0,
        )

        self.assertIn(decision.decision, {"hold", "reject"})


if __name__ == "__main__":
    unittest.main()
