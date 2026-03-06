import unittest

from app.interfaces import (
    EventClassifier,
    MarketContextProvider,
    NewsIngestion,
    PairImpactExtractor,
    SignalEngine,
    SignalPublisher,
)


class InterfaceImportTests(unittest.TestCase):
    def test_interfaces_import(self):
        self.assertIsNotNone(NewsIngestion)
        self.assertIsNotNone(PairImpactExtractor)
        self.assertIsNotNone(EventClassifier)
        self.assertIsNotNone(MarketContextProvider)
        self.assertIsNotNone(SignalEngine)
        self.assertIsNotNone(SignalPublisher)


if __name__ == "__main__":
    unittest.main()
