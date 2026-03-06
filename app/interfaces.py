from __future__ import annotations

from typing import Protocol

from app.schemas import MarketContext, NormalizedArticle, PairImpact, SignalCandidate


class NewsIngestion(Protocol):
    def fetch_forex_news(self) -> list[NormalizedArticle]:
        ...


class PairImpactExtractor(Protocol):
    def extract_pair_impacts(self, article: NormalizedArticle) -> list[PairImpact]:
        ...


class EventClassifier(Protocol):
    def classify_event_type(self, text: str) -> str:
        ...

    def score_event_impact(
        self,
        event_type: str,
        text: str,
        has_explicit_pair: bool,
        mention_strength: float,
    ) -> float:
        ...


class MarketContextProvider(Protocol):
    def build_context(self, pairs: list[str]) -> list[MarketContext]:
        ...


class SignalEngine(Protocol):
    def generate_signals(
        self, pair_impacts: list[PairImpact], contexts: list[MarketContext]
    ) -> list[SignalCandidate]:
        ...


class SignalPublisher(Protocol):
    def publish_signals(self, signals: list[SignalCandidate]) -> dict[str, int]:
        ...
