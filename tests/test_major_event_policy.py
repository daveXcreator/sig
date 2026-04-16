import unittest
from types import SimpleNamespace

from app.major_event_policy import select_publishable_signals_by_strategy
from app.schemas import MarketContext, NormalizedArticle, PairImpact, SignalCandidate


def _strategy_stub() -> SimpleNamespace:
    return SimpleNamespace(
        raw={
            "volatility_buckets": {"low_max_atr_percentile": 0.33, "normal_max_atr_percentile": 0.66},
            "trend_alignment": {"bullish_min_trend_score": 0.52, "bearish_max_trend_score": 0.48},
        },
        event_universe={
            "primary": ["rate_decision", "inflation", "employment", "geopolitical"],
            "secondary": ["risk_sentiment"],
            "blocked": ["other"],
            "secondary_rules": {"event_impact_min": 0.75, "pair_relevance_min": 0.7, "impact_now_min": 0.65},
        },
        hard_gate={
            "event_impact_min": 0.60,
            "pair_relevance_min": 0.55,
            "impact_now_min": 0.50,
            "allowed_latency_classes": ["immediate", "short_lag"],
            "freshness_max_minutes": 1440,
            "source_reliability_min": 0.60,
        },
        publish_thresholds={
            "low": {"confidence_min": 0.58, "technical_alignment_min": 0.40},
            "normal": {"confidence_min": 0.62, "technical_alignment_min": 0.45},
            "high": {"confidence_min": 0.66, "technical_alignment_min": 0.50},
        },
    )


class MajorEventPolicyTests(unittest.TestCase):
    def test_select_publishable_signals_allows_major_event_that_passes_thresholds(self):
        strategy = _strategy_stub()
        article = NormalizedArticle(
            article_id="a1",
            source="NewsAPI",
            url="https://example.com/a1",
            title="US payroll surprise boosts dollar",
            summary="Employment upside reprices rates.",
            published_at="2026-03-01T18:00:00Z",
            fetched_at="2026-03-01T18:10:00Z",
            language="en",
            source_reliability=0.8,
        )
        impact = PairImpact(
            article_id="a1",
            pair="USD/JPY",
            direction_hint="bullish",
            pair_relevance_score=0.82,
            event_type="employment",
            event_impact_score=0.83,
            explanation="fixture",
        )
        context = MarketContext(
            pair="USD/JPY",
            timestamp="2026-03-01T18:11:00Z",
            rsi=62.0,
            trend_score=0.67,
            volatility_regime="normal",
            atr_percentile=0.55,
            technical_alignment_score=0.72,
        )
        signal = SignalCandidate(
            signal_id="sig_1",
            pair="USD/JPY",
            direction="bullish",
            horizon="intraday",
            confidence_raw=0.78,
            confidence_calibrated=0.75,
            thesis="fixture",
            invalidation="fixture",
            reasons=["event=employment"],
            created_at="2026-03-01T18:12:00Z",
        )
        decision = SimpleNamespace(
            decision="publish",
            confidence_calibrated=0.75,
            signal=signal,
            impact_timing=SimpleNamespace(impact_now_score=0.78, impact_latency_class="immediate"),
        )

        result = select_publishable_signals_by_strategy(
            decisions=[decision],
            pair_impacts=[impact],
            contexts=[context],
            articles=[article],
            strategy=strategy,
        )

        self.assertEqual(1, len(result.signals))
        self.assertEqual(1, result.stats["published"])

    def test_select_publishable_signals_rejects_non_major_event(self):
        strategy = _strategy_stub()
        article = NormalizedArticle(
            article_id="a1",
            source="NewsAPI",
            url="https://example.com/a1",
            title="Weekly pair outlook",
            summary="Commentary with no macro release.",
            published_at="2026-03-01T18:00:00Z",
            fetched_at="2026-03-01T18:05:00Z",
            language="en",
            source_reliability=0.8,
        )
        impact = PairImpact(
            article_id="a1",
            pair="EUR/USD",
            direction_hint="bullish",
            pair_relevance_score=0.9,
            event_type="other",
            event_impact_score=0.9,
            explanation="fixture",
        )
        context = MarketContext(
            pair="EUR/USD",
            timestamp="2026-03-01T18:06:00Z",
            rsi=60.0,
            trend_score=0.68,
            volatility_regime="normal",
            atr_percentile=0.55,
            technical_alignment_score=0.72,
        )
        signal = SignalCandidate(
            signal_id="sig_2",
            pair="EUR/USD",
            direction="bullish",
            horizon="intraday",
            confidence_raw=0.8,
            confidence_calibrated=0.77,
            thesis="fixture",
            invalidation="fixture",
            reasons=["event=other"],
            created_at="2026-03-01T18:07:00Z",
        )
        decision = SimpleNamespace(
            decision="publish",
            confidence_calibrated=0.77,
            signal=signal,
            impact_timing=SimpleNamespace(impact_now_score=0.80, impact_latency_class="immediate"),
        )

        result = select_publishable_signals_by_strategy(
            decisions=[decision],
            pair_impacts=[impact],
            contexts=[context],
            articles=[article],
            strategy=strategy,
        )

        self.assertEqual([], result.signals)
        self.assertEqual(1, result.stats["failed_event_universe"])
        self.assertEqual(1, len(result.drop_details))
        self.assertEqual("policy", result.drop_details[0]["stage"])
        self.assertEqual("event_universe", result.drop_details[0]["reason"])

    def test_select_publishable_signals_tracks_hard_gate_breakdown(self):
        strategy = _strategy_stub()
        article = NormalizedArticle(
            article_id="a2",
            source="GoogleNews",
            url="https://example.com/a2",
            title="Fed officials discuss rates",
            summary="Macro chatter around USD and policy expectations.",
            published_at="2026-02-28T16:00:00Z",
            fetched_at="2026-03-01T18:05:00Z",
            language="en",
            source_reliability=0.8,
        )
        impact = PairImpact(
            article_id="a2",
            pair="USD/JPY",
            direction_hint="bullish",
            pair_relevance_score=0.82,
            event_type="rate_decision",
            event_impact_score=0.83,
            explanation="fixture",
        )
        context = MarketContext(
            pair="USD/JPY",
            timestamp="2026-03-01T18:06:00Z",
            rsi=62.0,
            trend_score=0.67,
            volatility_regime="normal",
            atr_percentile=0.55,
            technical_alignment_score=0.72,
        )
        signal = SignalCandidate(
            signal_id="sig_3",
            pair="USD/JPY",
            direction="bullish",
            horizon="intraday",
            confidence_raw=0.78,
            confidence_calibrated=0.75,
            thesis="fixture",
            invalidation="fixture",
            reasons=["event=rate_decision"],
            created_at="2026-03-01T18:07:00Z",
        )
        decision = SimpleNamespace(
            decision="publish",
            confidence_calibrated=0.75,
            signal=signal,
            impact_timing=SimpleNamespace(impact_now_score=0.78, impact_latency_class="immediate"),
        )

        result = select_publishable_signals_by_strategy(
            decisions=[decision],
            pair_impacts=[impact],
            contexts=[context],
            articles=[article],
            strategy=strategy,
        )

        self.assertEqual([], result.signals)
        self.assertEqual(1, result.stats["failed_hard_gate"])
        self.assertEqual(1, result.stats["failed_hard_gate_breakdown"].get("freshness_stale", 0))
        self.assertEqual(1, len(result.drop_details))
        self.assertEqual("policy", result.drop_details[0]["stage"])
        self.assertEqual("hard_gate_freshness_stale", result.drop_details[0]["reason"])

    def test_select_publishable_signals_tracks_threshold_subreason(self):
        strategy = _strategy_stub()
        article = NormalizedArticle(
            article_id="a3",
            source="NewsAPI",
            url="https://example.com/a3",
            title="Dollar reacts to macro surprise",
            summary="Macro move with weak chart confirmation.",
            published_at="2026-03-01T18:00:00Z",
            fetched_at="2026-03-01T18:05:00Z",
            language="en",
            source_reliability=0.8,
        )
        impact = PairImpact(
            article_id="a3",
            pair="USD/JPY",
            direction_hint="bullish",
            pair_relevance_score=0.82,
            event_type="employment",
            event_impact_score=0.83,
            explanation="fixture",
        )
        context = MarketContext(
            pair="USD/JPY",
            timestamp="2026-03-01T18:06:00Z",
            rsi=60.0,
            trend_score=0.67,
            volatility_regime="normal",
            atr_percentile=0.55,
            technical_alignment_score=0.38,
        )
        signal = SignalCandidate(
            signal_id="sig_4",
            pair="USD/JPY",
            direction="bullish",
            horizon="intraday",
            confidence_raw=0.8,
            confidence_calibrated=0.77,
            thesis="fixture",
            invalidation="fixture",
            reasons=["event=employment"],
            created_at="2026-03-01T18:07:00Z",
        )
        decision = SimpleNamespace(
            decision="publish",
            confidence_calibrated=0.77,
            signal=signal,
            impact_timing=SimpleNamespace(impact_now_score=0.78, impact_latency_class="immediate"),
        )

        result = select_publishable_signals_by_strategy(
            decisions=[decision],
            pair_impacts=[impact],
            contexts=[context],
            articles=[article],
            strategy=strategy,
        )

        self.assertEqual([], result.signals)
        self.assertEqual(1, result.stats["failed_thresholds"])
        self.assertEqual(1, len(result.drop_details))
        self.assertEqual("policy", result.drop_details[0]["stage"])
        self.assertEqual("threshold_technical_alignment_low", result.drop_details[0]["reason"])


if __name__ == "__main__":
    unittest.main()
