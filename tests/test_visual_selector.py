import unittest

from app.schemas import NormalizedArticle, PairImpact, SignalCandidate
from app.signal_setup import SignalExecutionPlan
from app.visual_selector import build_visual_attachment


def _article(title: str, summary: str = "fixture summary") -> NormalizedArticle:
    return NormalizedArticle(
        article_id="article_1",
        source="NewsAPI",
        url="https://example.com/news",
        title=title,
        summary=summary,
        published_at="2026-03-04T10:00:00Z",
        fetched_at="2026-03-04T10:01:00Z",
        language="en",
        source_reliability=0.8,
    )


def _pair_impact(event_type: str = "rate_decision") -> PairImpact:
    return PairImpact(
        article_id="article_1",
        pair="USD/JPY",
        direction_hint="bullish",
        pair_relevance_score=0.82,
        event_type=event_type,
        event_impact_score=0.78,
        explanation="fixture",
    )


def _signal(direction: str = "bullish") -> SignalCandidate:
    return SignalCandidate(
        signal_id="sig_1",
        pair="USD/JPY",
        direction=direction,
        horizon="intraday",
        confidence_raw=0.74,
        confidence_calibrated=0.72,
        thesis="fixture thesis",
        invalidation="close against setup on 1h",
        reasons=["event=rate_decision"],
        created_at="2026-03-04T10:02:00Z",
    )


def _execution_plan() -> SignalExecutionPlan:
    return SignalExecutionPlan(
        signal_id="sig_1",
        pair="USD/JPY",
        direction="bullish",
        entry_trigger_price=148.2,
        risk_line_price=147.6,
        valid_for_hours=8,
        valid_until="2026-03-04T18:02:00Z",
        when_to_enter="Enter after bullish break.",
        risk_line_text="Exit below risk line.",
        volatility_bucket="normal",
    )


class VisualSelectorTests(unittest.TestCase):
    def test_context_mode_uses_person_image_when_mentioned(self):
        visual = build_visual_attachment(
            article=_article("Trump comments move the dollar"),
            pair_impact=_pair_impact(),
            signal=_signal(),
            execution_plan=None,
            image_mode="context",
            enable_chart_images=True,
        )
        self.assertIsNotNone(visual)
        self.assertEqual("person", visual.kind)
        self.assertIn("Trump", visual.hint)

    def test_chart_mode_returns_quickchart_url(self):
        visual = build_visual_attachment(
            article=_article("USD/JPY setup into major US data"),
            pair_impact=_pair_impact(),
            signal=_signal(),
            execution_plan=_execution_plan(),
            image_mode="chart",
            enable_chart_images=True,
        )
        self.assertIsNotNone(visual)
        self.assertEqual("chart", visual.kind)
        self.assertEqual("quickchart", visual.source)
        self.assertIn("quickchart.io/chart", visual.image_url)

    def test_auto_mode_prefers_theme_for_geopolitical_event(self):
        visual = build_visual_attachment(
            article=_article("War tensions escalate in key region"),
            pair_impact=_pair_impact(event_type="geopolitical"),
            signal=_signal(),
            execution_plan=_execution_plan(),
            image_mode="auto",
            enable_chart_images=True,
        )
        self.assertIsNotNone(visual)
        self.assertIn(visual.kind, {"theme", "person"})


if __name__ == "__main__":
    unittest.main()
