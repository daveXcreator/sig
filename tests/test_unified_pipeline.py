from types import SimpleNamespace
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from app.schemas import SignalCandidate
from app.unified_pipeline import run_live_v2


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class UnifiedPipelineTests(unittest.TestCase):
    @patch("app.unified_pipeline.OPENAI_API_KEY", None)
    def test_run_live_v2_requires_openai_key(self):
        result = run_live_v2(enable_x=False)
        self.assertEqual("failed", result["status"])
        self.assertEqual("missing_openai_key", result["reason"])

    @patch("app.unified_pipeline.SignalPublisher")
    @patch("app.unified_pipeline.WeightedSignalEngine")
    @patch("app.unified_pipeline.TradeTracker")
    @patch("app.unified_pipeline.build_execution_plans")
    @patch("app.unified_pipeline.AlphaVantageIntradayProvider")
    @patch("app.unified_pipeline.load_major_event_strategy")
    @patch("app.unified_pipeline.AlphaVantageMarketContextProvider")
    @patch("app.unified_pipeline.FmpEconomicCalendarClient")
    @patch("app.unified_pipeline.analyze_sentiment")
    @patch("app.unified_pipeline.detect_currency_pairs")
    @patch("app.unified_pipeline.fetch_forex_news")
    @patch("app.unified_pipeline.OPENAI_API_KEY", "dummy")
    def test_run_live_v2_happy_path(
        self,
        fetch_news_mock,
        detect_pairs_mock,
        sentiment_mock,
        calendar_client_cls_mock,
        context_provider_cls_mock,
        load_strategy_mock,
        _load_intraday_provider_mock,
        build_execution_plans_mock,
        trade_tracker_cls_mock,
        engine_cls_mock,
        publisher_cls_mock,
    ):
        now = _now_utc_iso()
        fetch_news_mock.return_value = [
            {
                "source": "NewsAPI",
                "title": "ECB hawkish stance lifts euro",
                "description": "Euro gains while dollar softens.",
                "url": "https://example.com/eurusd",
                "published_at": now,
            }
        ]
        detect_pairs_mock.return_value = ["EUR/USD"]
        sentiment_mock.return_value = [
            {"pair": "EUR/USD", "sentiment": "bullish", "confidence": 0.83}
        ]

        context_provider = context_provider_cls_mock.return_value
        context_provider.build_context.return_value = []
        context_provider.build_context.return_value = [
            SimpleNamespace(
                pair="EUR/USD",
                timestamp="2026-02-28T00:10:00Z",
                rsi=64.0,
                trend_score=0.72,
                volatility_regime="normal",
                atr_percentile=0.55,
                technical_alignment_score=0.78,
            )
        ]
        calendar_client = calendar_client_cls_mock.return_value
        calendar_client.fetch_recent_window.return_value = []
        load_strategy_mock.return_value = SimpleNamespace(
            raw={
                "volatility_buckets": {"low_max_atr_percentile": 0.33, "normal_max_atr_percentile": 0.66},
                "trend_alignment": {"bullish_min_trend_score": 0.52, "bearish_max_trend_score": 0.48},
            },
            event_universe={
                "primary": ["rate_decision", "inflation", "employment", "geopolitical"],
                "secondary": ["risk_sentiment"],
                "blocked": ["other"],
                "secondary_rules": {"event_impact_min": 0.85, "pair_relevance_min": 0.8, "impact_now_min": 0.75},
            },
            hard_gate={
                "event_impact_min": 0.75,
                "pair_relevance_min": 0.7,
                "impact_now_min": 0.65,
                "allowed_latency_classes": ["immediate"],
                "freshness_max_minutes": 120,
                "source_reliability_min": 0.7,
            },
            publish_thresholds={
                "low": {"confidence_min": 0.7, "technical_alignment_min": 0.58},
                "normal": {"confidence_min": 0.73, "technical_alignment_min": 0.62},
                "high": {"confidence_min": 0.76, "technical_alignment_min": 0.66},
            },
        )

        signal = SignalCandidate(
            signal_id="sig_test",
            pair="EUR/USD",
            direction="bullish",
            horizon="intraday",
            confidence_raw=0.74,
            confidence_calibrated=0.71,
            thesis="rate_decision signal with technical confirmation",
            invalidation="Invalidate if 1h candle closes against direction with weak momentum.",
            reasons=["fixture"],
            created_at="2026-02-28T00:11:00Z",
        )
        engine = engine_cls_mock.return_value
        engine.evaluate_signals.return_value = [
            SimpleNamespace(
                decision="publish",
                confidence_calibrated=0.74,
                signal=signal,
                impact_timing=SimpleNamespace(impact_now_score=0.8, impact_latency_class="immediate"),
            )
        ]
        build_execution_plans_mock.return_value = {
            "sig_test": SimpleNamespace(signal_id="sig_test")
        }
        trade_tracker = trade_tracker_cls_mock.return_value
        trade_tracker.evaluate_open_trades.return_value = []
        trade_tracker.register_new_plans.return_value = 1
        trade_tracker.count_active.return_value = 1

        publisher = publisher_cls_mock.return_value
        publisher.publish_trade_result_updates.return_value = {"telegram": 0, "x": 0}
        publisher.publish_market_narrative.return_value = {"telegram": 1, "x": 0}

        result = run_live_v2(enable_x=False)

        self.assertEqual("ok", result["status"])
        self.assertEqual(1, result["articles"])
        self.assertEqual(1, result["publishable_signals"])
        self.assertEqual({"telegram": 1, "x": 0, "results": 0}, result["publish_stats"])
        self.assertIn("calendar_events", result)
        self.assertIn("news_briefs_published", result)
        self.assertIn("verdicts_published", result)
        self.assertIn("signal_alerts_published", result)
        self.assertEqual(1, result["policy_published"])
        self.assertIn("run_id", result)
        self.assertIn("stage_latency_ms", result)
        self.assertIn("total_latency_ms", result)
        self.assertIn("run_metrics", result)
        self.assertIn("coverage_metrics", result)
        self.assertIn("ingestion", result["stage_latency_ms"])
        self.assertIn("publishing", result["stage_latency_ms"])
        self.assertGreaterEqual(result["total_latency_ms"], 0)
        self.assertIn("major_event_articles", result["coverage_metrics"])
        self.assertIn("source_counts", result["coverage_metrics"])

    @patch("app.unified_pipeline.SignalPublisher")
    @patch("app.unified_pipeline.WeightedSignalEngine")
    @patch("app.unified_pipeline.TradeTracker")
    @patch("app.unified_pipeline.build_execution_plans")
    @patch("app.unified_pipeline.AlphaVantageIntradayProvider")
    @patch("app.unified_pipeline.load_major_event_strategy")
    @patch("app.unified_pipeline.AlphaVantageMarketContextProvider")
    @patch("app.unified_pipeline.FmpEconomicCalendarClient")
    @patch("app.unified_pipeline.analyze_sentiment")
    @patch("app.unified_pipeline.detect_currency_pairs")
    @patch("app.unified_pipeline.fetch_forex_news")
    @patch("app.unified_pipeline.OPENAI_API_KEY", "dummy")
    def test_run_live_v2_respects_runtime_publish_guardrail(
        self,
        fetch_news_mock,
        detect_pairs_mock,
        sentiment_mock,
        calendar_client_cls_mock,
        context_provider_cls_mock,
        load_strategy_mock,
        _load_intraday_provider_mock,
        build_execution_plans_mock,
        trade_tracker_cls_mock,
        engine_cls_mock,
        publisher_cls_mock,
    ):
        now = _now_utc_iso()
        fetch_news_mock.return_value = [
            {
                "source": "NewsAPI",
                "title": "ECB hawkish stance lifts euro",
                "description": "Euro gains while dollar softens.",
                "url": "https://example.com/eurusd",
                "published_at": now,
            }
        ]
        detect_pairs_mock.return_value = ["EUR/USD"]
        sentiment_mock.return_value = [{"pair": "EUR/USD", "sentiment": "bullish", "confidence": 0.83}]
        calendar_client_cls_mock.return_value.fetch_recent_window.return_value = []
        context_provider_cls_mock.return_value.build_context.return_value = [
            SimpleNamespace(
                pair="EUR/USD",
                timestamp="2026-02-28T00:10:00Z",
                rsi=64.0,
                trend_score=0.72,
                volatility_regime="normal",
                atr_percentile=0.55,
                technical_alignment_score=0.78,
            )
        ]
        load_strategy_mock.return_value = SimpleNamespace(
            raw={
                "volatility_buckets": {"low_max_atr_percentile": 0.33, "normal_max_atr_percentile": 0.66},
                "trend_alignment": {"bullish_min_trend_score": 0.52, "bearish_max_trend_score": 0.48},
            },
            event_universe={
                "primary": ["rate_decision", "inflation", "employment", "geopolitical"],
                "secondary": ["risk_sentiment"],
                "blocked": ["other"],
                "secondary_rules": {"event_impact_min": 0.85, "pair_relevance_min": 0.8, "impact_now_min": 0.75},
            },
            hard_gate={
                "event_impact_min": 0.75,
                "pair_relevance_min": 0.7,
                "impact_now_min": 0.65,
                "allowed_latency_classes": ["immediate"],
                "freshness_max_minutes": 120,
                "source_reliability_min": 0.7,
            },
            publish_thresholds={
                "low": {"confidence_min": 0.7, "technical_alignment_min": 0.58},
                "normal": {"confidence_min": 0.73, "technical_alignment_min": 0.62},
                "high": {"confidence_min": 0.76, "technical_alignment_min": 0.66},
            },
        )

        signal = SignalCandidate(
            signal_id="sig_guardrail",
            pair="EUR/USD",
            direction="bullish",
            horizon="intraday",
            confidence_raw=0.74,
            confidence_calibrated=0.71,
            thesis="rate_decision signal with technical confirmation",
            invalidation="Invalidate if 1h candle closes against direction with weak momentum.",
            reasons=["fixture"],
            created_at="2026-02-28T00:11:00Z",
        )
        engine_cls_mock.return_value.evaluate_signals.return_value = [
            SimpleNamespace(
                decision="publish",
                confidence_calibrated=0.74,
                signal=signal,
                impact_timing=SimpleNamespace(impact_now_score=0.8, impact_latency_class="immediate"),
            )
        ]
        build_execution_plans_mock.return_value = {"sig_guardrail": SimpleNamespace(signal_id="sig_guardrail")}
        trade_tracker = trade_tracker_cls_mock.return_value
        trade_tracker.evaluate_open_trades.return_value = []
        trade_tracker.register_new_plans.return_value = 1
        trade_tracker.count_active.return_value = 1

        result = run_live_v2(enable_x=False, publish_enabled=False)

        publisher_cls_mock.assert_not_called()
        self.assertFalse(result["publishing_enabled"])
        self.assertEqual("publish_disabled_runtime", result["publish_guardrail_reason"])
        self.assertEqual({"telegram": 0, "x": 0, "results": 0}, result["publish_stats"])
        self.assertEqual(1, result["publish_candidate_signals"])
        self.assertEqual(1, result["publishable_signals"])

    @patch("app.unified_pipeline.SignalPublisher")
    @patch("app.unified_pipeline.WeightedSignalEngine")
    @patch("app.unified_pipeline.TradeTracker")
    @patch("app.unified_pipeline.build_execution_plans")
    @patch("app.unified_pipeline.AlphaVantageIntradayProvider")
    @patch("app.unified_pipeline.load_major_event_strategy")
    @patch("app.unified_pipeline.AlphaVantageMarketContextProvider")
    @patch("app.unified_pipeline.FmpEconomicCalendarClient")
    @patch("app.unified_pipeline.analyze_sentiment")
    @patch("app.unified_pipeline.detect_currency_pairs")
    @patch("app.unified_pipeline.fetch_forex_news")
    @patch("app.unified_pipeline.ROLLBACK_SWITCH_ACTIVE", True)
    @patch("app.unified_pipeline.OPENAI_API_KEY", "dummy")
    def test_run_live_v2_respects_env_rollback_guardrail(
        self,
        fetch_news_mock,
        detect_pairs_mock,
        sentiment_mock,
        calendar_client_cls_mock,
        context_provider_cls_mock,
        load_strategy_mock,
        _load_intraday_provider_mock,
        build_execution_plans_mock,
        trade_tracker_cls_mock,
        engine_cls_mock,
        publisher_cls_mock,
    ):
        now = _now_utc_iso()
        fetch_news_mock.return_value = [
            {
                "source": "NewsAPI",
                "title": "ECB hawkish stance lifts euro",
                "description": "Euro gains while dollar softens.",
                "url": "https://example.com/eurusd",
                "published_at": now,
            }
        ]
        detect_pairs_mock.return_value = ["EUR/USD"]
        sentiment_mock.return_value = [{"pair": "EUR/USD", "sentiment": "bullish", "confidence": 0.83}]
        calendar_client_cls_mock.return_value.fetch_recent_window.return_value = []
        context_provider_cls_mock.return_value.build_context.return_value = [
            SimpleNamespace(
                pair="EUR/USD",
                timestamp="2026-02-28T00:10:00Z",
                rsi=64.0,
                trend_score=0.72,
                volatility_regime="normal",
                atr_percentile=0.55,
                technical_alignment_score=0.78,
            )
        ]
        load_strategy_mock.return_value = SimpleNamespace(
            raw={
                "volatility_buckets": {"low_max_atr_percentile": 0.33, "normal_max_atr_percentile": 0.66},
                "trend_alignment": {"bullish_min_trend_score": 0.52, "bearish_max_trend_score": 0.48},
            },
            event_universe={
                "primary": ["rate_decision", "inflation", "employment", "geopolitical"],
                "secondary": ["risk_sentiment"],
                "blocked": ["other"],
                "secondary_rules": {"event_impact_min": 0.85, "pair_relevance_min": 0.8, "impact_now_min": 0.75},
            },
            hard_gate={
                "event_impact_min": 0.75,
                "pair_relevance_min": 0.7,
                "impact_now_min": 0.65,
                "allowed_latency_classes": ["immediate"],
                "freshness_max_minutes": 120,
                "source_reliability_min": 0.7,
            },
            publish_thresholds={
                "low": {"confidence_min": 0.7, "technical_alignment_min": 0.58},
                "normal": {"confidence_min": 0.73, "technical_alignment_min": 0.62},
                "high": {"confidence_min": 0.76, "technical_alignment_min": 0.66},
            },
        )

        signal = SignalCandidate(
            signal_id="sig_env_rollback",
            pair="EUR/USD",
            direction="bullish",
            horizon="intraday",
            confidence_raw=0.74,
            confidence_calibrated=0.71,
            thesis="rate_decision signal with technical confirmation",
            invalidation="Invalidate if 1h candle closes against direction with weak momentum.",
            reasons=["fixture"],
            created_at="2026-02-28T00:11:00Z",
        )
        engine_cls_mock.return_value.evaluate_signals.return_value = [
            SimpleNamespace(
                decision="publish",
                confidence_calibrated=0.74,
                signal=signal,
                impact_timing=SimpleNamespace(impact_now_score=0.8, impact_latency_class="immediate"),
            )
        ]
        build_execution_plans_mock.return_value = {"sig_env_rollback": SimpleNamespace(signal_id="sig_env_rollback")}
        trade_tracker = trade_tracker_cls_mock.return_value
        trade_tracker.evaluate_open_trades.return_value = []
        trade_tracker.register_new_plans.return_value = 1
        trade_tracker.count_active.return_value = 1

        result = run_live_v2(enable_x=False, publish_enabled=True)

        publisher_cls_mock.assert_not_called()
        self.assertFalse(result["publishing_enabled"])
        self.assertEqual("rollback_switch_active_env", result["publish_guardrail_reason"])
        self.assertTrue(result["rollback_switch_active"])
        self.assertEqual(1, result["signal_drop_counts"].get("publishing_guardrail"))
        self.assertGreaterEqual(result["signal_drop_total"], 1)
        self.assertEqual(1, result["signal_drop_counts"].get("publishing_guardrail"))

    @patch("app.unified_pipeline.SignalPublisher")
    @patch("app.unified_pipeline.WeightedSignalEngine")
    @patch("app.unified_pipeline.TradeTracker")
    @patch("app.unified_pipeline.build_execution_plans")
    @patch("app.unified_pipeline.AlphaVantageIntradayProvider")
    @patch("app.unified_pipeline.load_major_event_strategy")
    @patch("app.unified_pipeline.AlphaVantageMarketContextProvider")
    @patch("app.unified_pipeline.FmpEconomicCalendarClient")
    @patch("app.unified_pipeline.analyze_sentiment")
    @patch("app.unified_pipeline.detect_currency_pairs")
    @patch("app.unified_pipeline.fetch_forex_news")
    @patch("app.unified_pipeline.OPENAI_API_KEY", "dummy")
    def test_run_live_v2_filters_non_tradable_pairs(
        self,
        fetch_news_mock,
        detect_pairs_mock,
        sentiment_mock,
        calendar_client_cls_mock,
        context_provider_cls_mock,
        load_strategy_mock,
        _load_intraday_provider_mock,
        build_execution_plans_mock,
        trade_tracker_cls_mock,
        engine_cls_mock,
        publisher_cls_mock,
    ):
        now = _now_utc_iso()
        fetch_news_mock.return_value = [
            {
                "source": "NewsAPI",
                "title": "Mixed FX flows across Asia",
                "description": "Some flows in USD/CNY and USD/JPY.",
                "url": "https://example.com/mixed",
                "published_at": now,
            }
        ]
        detect_pairs_mock.return_value = ["USD/CNY", "USD/JPY"]
        sentiment_mock.return_value = [
            {"pair": "USD/JPY", "sentiment": "bullish", "confidence": 0.8}
        ]
        calendar_client_cls_mock.return_value.fetch_recent_window.return_value = []
        context_provider_cls_mock.return_value.build_context.return_value = []
        load_strategy_mock.return_value = SimpleNamespace(
            raw={
                "volatility_buckets": {"low_max_atr_percentile": 0.33, "normal_max_atr_percentile": 0.66},
                "trend_alignment": {"bullish_min_trend_score": 0.52, "bearish_max_trend_score": 0.48},
            },
            event_universe={
                "primary": ["rate_decision", "inflation", "employment", "geopolitical"],
                "secondary": ["risk_sentiment"],
                "blocked": ["other"],
                "secondary_rules": {"event_impact_min": 0.85, "pair_relevance_min": 0.8, "impact_now_min": 0.75},
            },
            hard_gate={
                "event_impact_min": 0.75,
                "pair_relevance_min": 0.7,
                "impact_now_min": 0.65,
                "allowed_latency_classes": ["immediate"],
                "freshness_max_minutes": 120,
                "source_reliability_min": 0.7,
            },
            publish_thresholds={
                "low": {"confidence_min": 0.7, "technical_alignment_min": 0.58},
                "normal": {"confidence_min": 0.73, "technical_alignment_min": 0.62},
                "high": {"confidence_min": 0.76, "technical_alignment_min": 0.66},
            },
        )
        build_execution_plans_mock.return_value = {}
        trade_tracker = trade_tracker_cls_mock.return_value
        trade_tracker.evaluate_open_trades.return_value = []
        trade_tracker.register_new_plans.return_value = 0
        trade_tracker.count_active.return_value = 0
        engine_cls_mock.return_value.evaluate_signals.return_value = []
        publisher_cls_mock.return_value.publish_trade_result_updates.return_value = {"telegram": 0, "x": 0}
        publisher_cls_mock.return_value.publish_market_narrative.return_value = {"telegram": 0, "x": 0}

        run_live_v2(enable_x=False)

        called_pairs = sentiment_mock.call_args[0][2]
        self.assertEqual(["USD/JPY"], called_pairs)

    @patch("app.unified_pipeline.SignalPublisher")
    @patch("app.unified_pipeline.WeightedSignalEngine")
    @patch("app.unified_pipeline.TradeTracker")
    @patch("app.unified_pipeline.build_execution_plans")
    @patch("app.unified_pipeline.AlphaVantageIntradayProvider")
    @patch("app.unified_pipeline.load_major_event_strategy")
    @patch("app.unified_pipeline.AlphaVantageMarketContextProvider")
    @patch("app.unified_pipeline.FmpEconomicCalendarClient")
    @patch("app.unified_pipeline.analyze_sentiment")
    @patch("app.unified_pipeline.detect_currency_pairs")
    @patch("app.unified_pipeline.fetch_forex_news")
    @patch("app.unified_pipeline.OPENAI_API_KEY", "dummy")
    def test_run_live_v2_prefilters_irrelevant_articles_before_openai(
        self,
        fetch_news_mock,
        detect_pairs_mock,
        sentiment_mock,
        calendar_client_cls_mock,
        context_provider_cls_mock,
        load_strategy_mock,
        _load_intraday_provider_mock,
        build_execution_plans_mock,
        trade_tracker_cls_mock,
        engine_cls_mock,
        publisher_cls_mock,
    ):
        now = _now_utc_iso()
        fetch_news_mock.return_value = [
            {
                "source": "NewsAPI",
                "title": "Celebrity gossip update",
                "description": "Entertainment news with no FX context.",
                "url": "https://example.com/irrelevant",
                "published_at": now,
            },
            {
                "source": "NewsAPI",
                "title": "Fed outlook supports USD/JPY",
                "description": "Policy expectations and rates discussion.",
                "url": "https://example.com/relevant",
                "published_at": now,
            },
        ]
        detect_pairs_mock.return_value = ["USD/JPY"]
        sentiment_mock.return_value = [
            {"pair": "USD/JPY", "sentiment": "bullish", "confidence": 0.8}
        ]
        calendar_client_cls_mock.return_value.fetch_recent_window.return_value = []
        context_provider_cls_mock.return_value.build_context.return_value = []
        load_strategy_mock.return_value = SimpleNamespace(
            raw={
                "volatility_buckets": {"low_max_atr_percentile": 0.33, "normal_max_atr_percentile": 0.66},
                "trend_alignment": {"bullish_min_trend_score": 0.52, "bearish_max_trend_score": 0.48},
            },
            event_universe={
                "primary": ["rate_decision", "inflation", "employment", "geopolitical"],
                "secondary": ["risk_sentiment"],
                "blocked": ["other"],
                "secondary_rules": {"event_impact_min": 0.85, "pair_relevance_min": 0.8, "impact_now_min": 0.75},
            },
            hard_gate={
                "event_impact_min": 0.75,
                "pair_relevance_min": 0.7,
                "impact_now_min": 0.65,
                "allowed_latency_classes": ["immediate"],
                "freshness_max_minutes": 120,
                "source_reliability_min": 0.7,
            },
            publish_thresholds={
                "low": {"confidence_min": 0.7, "technical_alignment_min": 0.58},
                "normal": {"confidence_min": 0.73, "technical_alignment_min": 0.62},
                "high": {"confidence_min": 0.76, "technical_alignment_min": 0.66},
            },
        )
        build_execution_plans_mock.return_value = {}
        trade_tracker = trade_tracker_cls_mock.return_value
        trade_tracker.evaluate_open_trades.return_value = []
        trade_tracker.register_new_plans.return_value = 0
        trade_tracker.count_active.return_value = 0
        engine_cls_mock.return_value.evaluate_signals.return_value = []
        publisher_cls_mock.return_value.publish_trade_result_updates.return_value = {"telegram": 0, "x": 0}
        publisher_cls_mock.return_value.publish_market_narrative.return_value = {"telegram": 0, "x": 0}

        run_live_v2(enable_x=False)

        self.assertEqual(1, detect_pairs_mock.call_count)


if __name__ == "__main__":
    unittest.main()
