from dataclasses import fields
import unittest

from app.schemas import (
    MarketContext,
    NormalizedArticle,
    PairImpact,
    SchemaValidationError,
    SignalCandidate,
)


class SchemaContractTests(unittest.TestCase):
    def test_normalized_article_contract(self):
        article = NormalizedArticle(
            article_id="a1",
            source="NewsAPI",
            url="https://example.com/article",
            title="ECB signals prolonged restrictive stance",
            summary="Short cleaned summary",
            published_at="2026-02-28T00:00:00Z",
            fetched_at="2026-02-28T00:01:00Z",
            language="en",
            source_reliability=0.8,
        )
        self.assertEqual(
            [
                "article_id",
                "source",
                "url",
                "title",
                "summary",
                "published_at",
                "fetched_at",
                "language",
                "source_reliability",
            ],
            [field.name for field in fields(NormalizedArticle)],
        )
        self.assertEqual("en", article.language)

    def test_pair_impact_contract(self):
        impact = PairImpact(
            article_id="a1",
            pair="eur/usd",
            direction_hint="bearish",
            pair_relevance_score=0.82,
            event_type="rate_decision",
            event_impact_score=0.74,
            explanation="Policy divergence pressure",
        )
        self.assertEqual(
            [
                "article_id",
                "pair",
                "direction_hint",
                "pair_relevance_score",
                "event_type",
                "event_impact_score",
                "explanation",
            ],
            [field.name for field in fields(PairImpact)],
        )
        self.assertEqual("EUR/USD", impact.pair)

    def test_market_context_contract(self):
        context = MarketContext(
            pair="EUR/USD",
            timestamp="2026-02-28T00:05:00Z",
            rsi=63.4,
            trend_score=0.58,
            volatility_regime="normal",
            atr_percentile=0.61,
            technical_alignment_score=0.66,
        )
        self.assertEqual(
            [
                "pair",
                "timestamp",
                "rsi",
                "trend_score",
                "volatility_regime",
                "atr_percentile",
                "technical_alignment_score",
            ],
            [field.name for field in fields(MarketContext)],
        )
        self.assertEqual("normal", context.volatility_regime)

    def test_signal_candidate_contract(self):
        candidate = SignalCandidate(
            signal_id="sig_20260228_0001",
            pair="EUR/USD",
            direction="bearish",
            horizon="intraday",
            confidence_raw=0.71,
            confidence_calibrated=0.68,
            thesis="Policy divergence pressure",
            invalidation="Close above 1.0945 on 1h candle",
            reasons=["High pair relevance", "Technical alignment positive"],
            created_at="2026-02-28T00:06:00Z",
        )
        self.assertEqual(
            [
                "signal_id",
                "pair",
                "direction",
                "horizon",
                "confidence_raw",
                "confidence_calibrated",
                "thesis",
                "invalidation",
                "reasons",
                "created_at",
            ],
            [field.name for field in fields(SignalCandidate)],
        )
        self.assertEqual(2, len(candidate.reasons))

    def test_schema_validation_rejects_bad_inputs(self):
        with self.assertRaises(SchemaValidationError):
            PairImpact(
                article_id="a1",
                pair="BADPAIR",
                direction_hint="bearish",
                pair_relevance_score=0.82,
                event_type="rate_decision",
                event_impact_score=0.74,
                explanation="Invalid pair should fail",
            )

        with self.assertRaises(SchemaValidationError):
            SignalCandidate(
                signal_id="sig_1",
                pair="EUR/USD",
                direction="bullish",
                horizon="intraday",
                confidence_raw=0.5,
                confidence_calibrated=0.5,
                thesis="Test",
                invalidation="Test",
                reasons=[],
                created_at="not-a-timestamp",
            )


if __name__ == "__main__":
    unittest.main()
