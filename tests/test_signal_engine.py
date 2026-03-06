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
        self.assertEqual("publish", classify_decision(0.67))
        self.assertEqual("hold", classify_decision(0.58))
        self.assertEqual("reject", classify_decision(0.579))

    def test_calibration_stays_in_bounds(self):
        self.assertGreaterEqual(calibrate_confidence(0.0), 0.0)
        self.assertLessEqual(calibrate_confidence(1.0), 1.0)

    def test_timing_gate_downgrades_publish(self):
        class _Timing:
            impact_latency_class = "short_lag"

        self.assertEqual("hold", apply_timing_gate("publish", _Timing()))


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
            pair_relevance=0.55,
            event_impact=0.50,
            direction_hint="neutral",
        )
        context = _context(
            pair="GBP/USD",
            trend_score=0.56,
            technical_alignment=0.48,
            volatility_regime="normal",
        )

        decision = self.engine.evaluate_pair(
            pair_impact=pair_impact,
            market_context=context,
            freshness=0.45,
            source_reliability=0.55,
        )

        self.assertEqual("hold", decision.decision)
        self.assertIsNotNone(decision.signal)
        self.assertGreaterEqual(decision.confidence_calibrated, 0.58)
        self.assertLess(decision.confidence_calibrated, 0.67)

    def test_reject_fixture(self):
        pair_impact = _pair_impact(
            pair="AUD/USD",
            pair_relevance=0.45,
            event_impact=0.35,
            direction_hint="bearish",
        )
        context = _context(
            pair="AUD/USD",
            trend_score=0.75,
            technical_alignment=0.35,
            volatility_regime="high",
        )

        decision = self.engine.evaluate_pair(
            pair_impact=pair_impact,
            market_context=context,
            freshness=0.30,
            source_reliability=0.40,
        )

        self.assertEqual("reject", decision.decision)
        self.assertIsNotNone(decision.signal)
        self.assertLess(decision.confidence_calibrated, 0.58)
        self.assertIsNotNone(decision.impact_timing)

    def test_generate_signals_returns_only_publish(self):
        impacts = [
            _pair_impact("EUR/USD", 0.92, 0.84, "bullish"),
            _pair_impact("GBP/USD", 0.55, 0.50, "neutral"),
            _pair_impact("AUD/USD", 0.45, 0.35, "bearish"),
        ]
        contexts = [
            _context("EUR/USD", 0.74, 0.86, "low"),
            _context("GBP/USD", 0.56, 0.48, "normal"),
            _context("AUD/USD", 0.75, 0.35, "high"),
        ]

        # Use defaults to preserve deterministic split.
        decisions = self.engine.evaluate_signals(
            impacts,
            contexts,
            freshness=0.70,
            source_reliability=0.75,
        )
        published = [d for d in decisions if d.decision == "publish"]
        self.assertEqual(1, len(published))

        signals = self.engine.generate_signals(impacts, contexts)
        self.assertEqual(1, len(signals))
        self.assertEqual("EUR/USD", signals[0].pair)

    def test_publish_downgraded_when_timing_not_immediate(self):
        pair_impact = PairImpact(
            article_id="a2",
            pair="EUR/USD",
            direction_hint="bullish",
            pair_relevance_score=0.95,
            event_type="other",
            event_impact_score=0.80,
            explanation="Routine commentary with no urgency",
        )
        context = _context(
            pair="EUR/USD",
            trend_score=0.80,
            technical_alignment=0.90,
            volatility_regime="low",
        )
        decision = self.engine.evaluate_pair(
            pair_impact=pair_impact,
            market_context=context,
            freshness=0.80,
            source_reliability=0.80,
            surprise_strength=0.0,
        )

        self.assertIn(decision.decision, {"hold", "reject"})


if __name__ == "__main__":
    unittest.main()
