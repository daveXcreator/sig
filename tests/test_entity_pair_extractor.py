import unittest

from app.entity_pair_extractor import DeterministicPairImpactExtractor
from app.schemas import NormalizedArticle


def _article(title: str, summary: str, article_id: str = "a1") -> NormalizedArticle:
    return NormalizedArticle(
        article_id=article_id,
        source="TestWire",
        url=f"https://example.com/{article_id}",
        title=title,
        summary=summary,
        published_at="2026-02-28T00:00:00Z",
        fetched_at="2026-02-28T00:01:00Z",
        language="en",
        source_reliability=0.8,
    )


class DeterministicPairExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = DeterministicPairImpactExtractor()

    def test_boj_yen_news_maps_to_usdjpy(self):
        article = _article(
            "Bank of Japan keeps rates unchanged as yen weakens",
            "BOJ signaled a dovish outlook and the Japanese yen fell.",
            "boj1",
        )

        impacts = self.extractor.extract_pair_impacts(article)
        pairs = [impact.pair for impact in impacts]

        self.assertIn("USD/JPY", pairs)

    def test_ecb_and_fed_news_maps_to_eurusd(self):
        article = _article(
            "ECB turns hawkish while Federal Reserve stays cautious",
            "Euro gains as policy divergence widens versus the U.S. dollar.",
            "ecb1",
        )

        impacts = self.extractor.extract_pair_impacts(article)
        pairs = [impact.pair for impact in impacts]

        self.assertIn("EUR/USD", pairs)

    def test_rba_alias_maps_to_audusd(self):
        article = _article(
            "RBA warns inflation remains sticky",
            "Australia central bank comments pushed the aussie lower.",
            "rba1",
        )

        impacts = self.extractor.extract_pair_impacts(article)
        pairs = [impact.pair for impact in impacts]

        self.assertIn("AUD/USD", pairs)

    def test_explicit_pair_mention_boosts_relevance(self):
        article = _article(
            "GBP/USD drops after weak UK growth data",
            "Sterling falls sharply as recession fears build.",
            "gbp1",
        )

        impacts = self.extractor.extract_pair_impacts(article)
        gbpusd = next((item for item in impacts if item.pair == "GBP/USD"), None)

        self.assertIsNotNone(gbpusd)
        self.assertGreaterEqual(gbpusd.pair_relevance_score, 0.95)

    def test_snb_news_maps_to_usdchf(self):
        article = _article(
            "Swiss National Bank signals patience on rates",
            "The Swiss franc traded lower after SNB remarks.",
            "snb1",
        )

        impacts = self.extractor.extract_pair_impacts(article)
        pairs = [impact.pair for impact in impacts]

        self.assertIn("USD/CHF", pairs)

    def test_geopolitical_risk_off_news_applies_direction_fallback(self):
        article = _article(
            "Missile attack escalates regional conflict and lifts yen demand",
            "Risk-off sentiment and flight to safety dominated flows in USD/JPY.",
            "geo1",
        )

        impacts = self.extractor.extract_pair_impacts(article)
        usdjpy = next((item for item in impacts if item.pair == "USD/JPY"), None)

        self.assertIsNotNone(usdjpy)
        self.assertEqual("bearish", usdjpy.direction_hint)


if __name__ == "__main__":
    unittest.main()
