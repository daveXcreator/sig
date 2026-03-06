import unittest
from unittest.mock import patch

from app.publisher import (
    DEFAULT_DISCLAIMER,
    PublisherConfig,
    SignalPublisher,
    _split_for_telegram,
    format_telegram_batch,
    format_telegram_market_update,
    format_telegram_news_brief,
    format_telegram_signal,
    format_x_signal,
)
from app.schemas import MarketContext, NormalizedArticle, PairImpact, SignalCandidate
from app.trade_tracker import TradeUpdate


def _signal(
    signal_id: str = "sig_20260228_0001",
    pair: str = "EUR/USD",
    direction: str = "bearish",
    confidence: float = 0.68,
) -> SignalCandidate:
    return SignalCandidate(
        signal_id=signal_id,
        pair=pair,
        direction=direction,
        horizon="intraday",
        confidence_raw=min(1.0, confidence + 0.02),
        confidence_calibrated=confidence,
        thesis="Policy divergence pressure with confirming momentum.",
        invalidation="Close above 1.0945 on 1h candle.",
        reasons=["High pair relevance", "Technical alignment positive"],
        created_at="2026-02-28T00:06:00Z",
    )


class PublisherFormattingTests(unittest.TestCase):
    def test_format_telegram_signal_snapshot(self):
        signal = _signal()
        actual = format_telegram_signal(signal)
        expected = (
            "*EUR/USD* | BEARISH | intraday\n"
            "Signal ID: `sig_20260228_0001`\n"
            "Confidence: `0.68`\n"
            "Thesis: Policy divergence pressure with confirming momentum.\n"
            "Invalidation: Close above 1.0945 on 1h candle.\n"
            "Time (UTC): 2026-02-28T00:06:00Z"
        )
        self.assertEqual(expected, actual)

    def test_format_telegram_batch_snapshot(self):
        signals = [_signal(), _signal(signal_id="sig_20260228_0002", pair="USD/JPY", direction="bullish", confidence=0.71)]
        actual = format_telegram_batch(signals, include_disclaimer=True)
        expected = (
            "Signalyze AI Free Signals\n\n"
            "*EUR/USD* | BEARISH | intraday\n"
            "Signal ID: `sig_20260228_0001`\n"
            "Confidence: `0.68`\n"
            "Thesis: Policy divergence pressure with confirming momentum.\n"
            "Invalidation: Close above 1.0945 on 1h candle.\n"
            "Time (UTC): 2026-02-28T00:06:00Z\n\n"
            "*USD/JPY* | BULLISH | intraday\n"
            "Signal ID: `sig_20260228_0002`\n"
            "Confidence: `0.71`\n"
            "Thesis: Policy divergence pressure with confirming momentum.\n"
            "Invalidation: Close above 1.0945 on 1h candle.\n"
            "Time (UTC): 2026-02-28T00:06:00Z\n\n"
            f"{DEFAULT_DISCLAIMER}"
        )
        self.assertEqual(expected, actual)

    def test_format_x_signal_length_bound(self):
        signal = _signal()
        text = format_x_signal(signal, include_disclaimer=True)
        self.assertLessEqual(len(text), 280)
        self.assertIn("id:sig_20260228_0001", text)

    def test_format_telegram_news_brief_snapshot(self):
        brief = {
            "post_id": "abc12345",
            "timestamp_utc": "2026-02-28T00:00:00Z",
            "headline": "ECB officials maintain hawkish bias after inflation surprise",
            "summary_1l": "Euro gained as markets repriced rate expectations.",
            "why_it_matters_fx": "Rate expectations can reprice EUR/USD quickly.",
            "affected_pairs": ["EUR/USD", "USD/JPY"],
            "impact_window": "immediate",
            "impact_level": "high",
            "source_name": "Reuters",
            "source_url": "https://example.com/news",
        }

        text = format_telegram_news_brief(brief)
        self.assertIn("News Brief", text)
        self.assertIn("Impact: high | immediate", text)
        self.assertIn("Source: Reuters - https://example.com/news", text)

    def test_format_telegram_market_update_sections(self):
        brief = {
            "post_id": "abc12345",
            "timestamp_utc": "2026-02-28T00:00:00Z",
            "headline": "ECB officials maintain hawkish bias after inflation surprise",
            "summary_1l": "Euro gained as markets repriced rate expectations.",
            "why_it_matters_fx": "Rate expectations can reprice EUR/USD quickly.",
            "affected_pairs": ["EUR/USD"],
            "impact_window": "immediate",
            "impact_level": "high",
            "source_name": "Reuters",
            "source_url": "https://example.com/news",
        }
        verdict = {
            "related_post_id": "abc12345",
            "pair": "EUR/USD",
            "bias": "bullish",
            "confidence": 0.77,
            "state": "watchlist",
            "thesis": "rate decision context supports a bullish bias",
            "trigger_condition": "Wait for cleaner candle confirmation.",
            "invalidation_condition": "Close below support on 1h candle.",
            "time_horizon": "intraday",
            "timestamp_utc": "2026-02-28T00:05:00Z",
        }

        text = format_telegram_market_update(
            briefs=[brief],
            verdicts=[verdict],
            signals=[_signal()],
            include_disclaimer=True,
        )

        self.assertIn("Signalyze AI Market Update", text)
        self.assertIn("News", text)
        self.assertIn("Verdicts", text)
        self.assertIn("Signal Alerts", text)
        self.assertIn(DEFAULT_DISCLAIMER, text)

    def test_split_for_telegram_long_message(self):
        long_text = ("abcde " * 900).strip()
        parts = _split_for_telegram(long_text, max_chars=500)

        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= 500 for part in parts))


class PublisherDispatchTests(unittest.TestCase):
    @patch("app.publisher.send_tweet")
    @patch("app.publisher.send_telegram_message")
    def test_publish_signals_telegram_only(self, telegram_mock, tweet_mock):
        telegram_mock.return_value = True
        tweet_mock.return_value = True

        publisher = SignalPublisher(
            PublisherConfig(enable_telegram=True, enable_x=False, include_disclaimer=True)
        )
        result = publisher.publish_signals([_signal(), _signal(signal_id="sig_2")])

        self.assertEqual({"telegram": 2, "x": 0}, result)
        telegram_mock.assert_called_once()
        tweet_mock.assert_not_called()

    @patch("app.publisher.send_tweet")
    @patch("app.publisher.send_telegram_message")
    def test_publish_signals_with_x_enabled(self, telegram_mock, tweet_mock):
        telegram_mock.return_value = True
        tweet_mock.return_value = True

        publisher = SignalPublisher(
            PublisherConfig(enable_telegram=True, enable_x=True, include_disclaimer=False)
        )
        result = publisher.publish_signals([_signal(), _signal(signal_id="sig_2")])

        self.assertEqual({"telegram": 2, "x": 2}, result)
        telegram_mock.assert_called_once()
        self.assertEqual(2, tweet_mock.call_count)

    @patch("app.publisher.send_telegram_message")
    def test_publish_market_narrative(self, telegram_mock):
        telegram_mock.return_value = True
        publisher = SignalPublisher(
            PublisherConfig(enable_telegram=True, enable_x=False, enable_images=False)
        )

        articles = [
            NormalizedArticle(
                article_id="article_1",
                source="NewsAPI",
                url="https://example.com/a1",
                title="ECB keeps hawkish tone",
                summary="Euro gains as rate outlook remains tight.",
                published_at="2026-02-28T00:00:00Z",
                fetched_at="2026-02-28T00:01:00Z",
                language="en",
                source_reliability=0.8,
            )
        ]
        impacts = [
            PairImpact(
                article_id="article_1",
                pair="EUR/USD",
                direction_hint="bullish",
                pair_relevance_score=0.82,
                event_type="rate_decision",
                event_impact_score=0.79,
                explanation="policy divergence",
            )
        ]
        contexts = [
            MarketContext(
                pair="EUR/USD",
                timestamp="2026-02-28T00:03:00Z",
                rsi=61.0,
                trend_score=0.71,
                volatility_regime="normal",
                atr_percentile=0.54,
                technical_alignment_score=0.75,
            )
        ]
        decisions = [
            unittest.mock.Mock(
                decision="publish",
                confidence_calibrated=0.73,
                signal=_signal(),
            )
        ]

        result = publisher.publish_market_narrative(
            articles=articles,
            impacts=impacts,
            contexts=contexts,
            decisions=decisions,
            signals=[_signal()],
        )

        self.assertEqual(1, result["telegram"])
        self.assertEqual(0, result["x"])
        self.assertGreaterEqual(result["news_briefs"], 1)
        self.assertGreaterEqual(result["verdicts"], 1)
        self.assertEqual(1, result["signal_alerts"])
        telegram_mock.assert_called_once()

        sent_text = telegram_mock.call_args[0][0]
        self.assertIn("News:", sent_text)
        self.assertIn("Summary:", sent_text)
        self.assertIn("Why It Matters:", sent_text)
        self.assertIn("Verdict:", sent_text)
        self.assertIn("Why This Verdict:", sent_text)
        self.assertNotIn("http://", sent_text)
        self.assertNotIn("https://", sent_text)
        self.assertNotIn("Confidence:", sent_text)
        self.assertNotIn("Signal ID:", sent_text)

    @patch("app.publisher.send_telegram_photo")
    @patch("app.publisher.send_telegram_message")
    def test_publish_market_narrative_with_images(self, telegram_mock, photo_mock):
        telegram_mock.return_value = True
        photo_mock.return_value = True

        publisher = SignalPublisher(
            PublisherConfig(
                enable_telegram=True,
                enable_x=False,
                enable_images=True,
                image_mode="context",
                enable_chart_images=True,
            )
        )

        articles = [
            NormalizedArticle(
                article_id="article_1",
                source="NewsAPI",
                url="https://example.com/a1",
                title="Powell comments support USD outlook",
                summary="USD remains firm as policy stance stays restrictive.",
                published_at="2026-02-28T00:00:00Z",
                fetched_at="2026-02-28T00:01:00Z",
                language="en",
                source_reliability=0.8,
            )
        ]
        impacts = [
            PairImpact(
                article_id="article_1",
                pair="EUR/USD",
                direction_hint="bearish",
                pair_relevance_score=0.82,
                event_type="rate_decision",
                event_impact_score=0.79,
                explanation="policy divergence",
            )
        ]
        contexts = [
            MarketContext(
                pair="EUR/USD",
                timestamp="2026-02-28T00:03:00Z",
                rsi=45.0,
                trend_score=0.38,
                volatility_regime="normal",
                atr_percentile=0.54,
                technical_alignment_score=0.75,
            )
        ]
        decisions = [
            unittest.mock.Mock(
                decision="publish",
                confidence_calibrated=0.73,
                signal=_signal(direction="bearish"),
            )
        ]

        result = publisher.publish_market_narrative(
            articles=articles,
            impacts=impacts,
            contexts=contexts,
            decisions=decisions,
            signals=[_signal(direction="bearish")],
        )

        self.assertEqual(1, result["telegram"])
        photo_mock.assert_called_once()

    @patch("app.publisher.send_telegram_message")
    def test_publish_market_narrative_splits_when_large(self, telegram_mock):
        telegram_mock.return_value = True
        publisher = SignalPublisher(
            PublisherConfig(
                enable_telegram=True,
                enable_x=False,
                max_news_briefs=12,
                max_verdicts=12,
                enable_images=False,
            )
        )

        articles = []
        impacts = []
        decisions = []
        contexts = [
            MarketContext(
                pair="EUR/USD",
                timestamp="2026-02-28T00:03:00Z",
                rsi=61.0,
                trend_score=0.71,
                volatility_regime="normal",
                atr_percentile=0.54,
                technical_alignment_score=0.75,
            ),
            MarketContext(
                pair="USD/JPY",
                timestamp="2026-02-28T00:03:00Z",
                rsi=58.0,
                trend_score=0.64,
                volatility_regime="normal",
                atr_percentile=0.51,
                technical_alignment_score=0.70,
            ),
        ]

        pairs = ["EUR/USD", "USD/JPY"]
        for idx in range(12):
            article_id = f"article_{idx}"
            pair = pairs[idx % 2]
            articles.append(
                NormalizedArticle(
                    article_id=article_id,
                    source="NewsAPI",
                    url=f"https://example.com/a{idx}",
                    title=f"Macro headline {idx} " + ("update " * 30),
                    summary="Summary " + ("detail " * 60),
                    published_at="2026-02-28T00:00:00Z",
                    fetched_at="2026-02-28T00:01:00Z",
                    language="en",
                    source_reliability=0.8,
                )
            )
            impacts.append(
                PairImpact(
                    article_id=article_id,
                    pair=pair,
                    direction_hint="bullish",
                    pair_relevance_score=0.82,
                    event_type="rate_decision",
                    event_impact_score=0.79,
                    explanation="policy divergence",
                )
            )
            signal = _signal(signal_id=f"sig_{idx}", pair=pair, direction="bullish", confidence=0.76)
            decisions.append(
                unittest.mock.Mock(
                    decision="publish",
                    confidence_calibrated=0.76,
                    signal=signal,
                )
            )

        result = publisher.publish_market_narrative(
            articles=articles,
            impacts=impacts,
            contexts=contexts,
            decisions=decisions,
            signals=[item.signal for item in decisions],
        )

        self.assertEqual(12, result["telegram"])
        self.assertGreaterEqual(telegram_mock.call_count, 2)

    @patch("app.publisher.send_telegram_message")
    def test_publish_trade_result_updates(self, telegram_mock):
        telegram_mock.return_value = True
        publisher = SignalPublisher(PublisherConfig(enable_telegram=True, enable_x=False))

        updates = [
            TradeUpdate(
                signal_id="sig_1",
                pair="USD/JPY",
                state="CLOSED_PROFIT",
                result_r_multiple=1.0,
                message="fixture",
            )
        ]
        result = publisher.publish_trade_result_updates(updates)

        self.assertEqual({"telegram": 1, "x": 0}, result)
        telegram_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
