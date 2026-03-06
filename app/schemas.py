from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import re
from typing import Literal


PAIR_PATTERN = re.compile(r"^[A-Z]{3}/[A-Z]{3}$")
EVENT_TYPES = {
    "rate_decision",
    "inflation",
    "employment",
    "geopolitical",
    "risk_sentiment",
    "other",
}
VOLATILITY_REGIMES = {"low", "normal", "high"}
HORIZONS = {"scalp", "intraday", "swing"}


class SchemaValidationError(ValueError):
    pass


def _require_non_empty_string(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_score(value: float, field_name: str) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        raise SchemaValidationError(f"{field_name} must be numeric") from None

    if score < 0.0 or score > 1.0:
        raise SchemaValidationError(f"{field_name} must be between 0 and 1")
    return score


def _require_iso8601_utc(value: str, field_name: str) -> str:
    text = _require_non_empty_string(value, field_name)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        datetime.fromisoformat(text)
    except ValueError:
        raise SchemaValidationError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from None
    return value


def _require_pair(value: str, field_name: str) -> str:
    pair = _require_non_empty_string(value, field_name).upper()
    if not PAIR_PATTERN.fullmatch(pair):
        raise SchemaValidationError(f"{field_name} must match AAA/BBB")
    return pair


@dataclass(slots=True)
class NormalizedArticle:
    article_id: str
    source: str
    url: str
    title: str
    summary: str
    published_at: str
    fetched_at: str
    language: str
    source_reliability: float

    def __post_init__(self) -> None:
        self.article_id = _require_non_empty_string(self.article_id, "article_id")
        self.source = _require_non_empty_string(self.source, "source")
        self.url = _require_non_empty_string(self.url, "url")
        self.title = _require_non_empty_string(self.title, "title")
        self.summary = _require_non_empty_string(self.summary, "summary")
        self.published_at = _require_iso8601_utc(self.published_at, "published_at")
        self.fetched_at = _require_iso8601_utc(self.fetched_at, "fetched_at")
        self.language = _require_non_empty_string(self.language, "language")
        self.source_reliability = _require_score(
            self.source_reliability, "source_reliability"
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class PairImpact:
    article_id: str
    pair: str
    direction_hint: Literal["bullish", "bearish", "neutral"]
    pair_relevance_score: float
    event_type: str
    event_impact_score: float
    explanation: str

    def __post_init__(self) -> None:
        self.article_id = _require_non_empty_string(self.article_id, "article_id")
        self.pair = _require_pair(self.pair, "pair")
        if self.direction_hint not in {"bullish", "bearish", "neutral"}:
            raise SchemaValidationError("direction_hint must be bullish/bearish/neutral")
        self.pair_relevance_score = _require_score(
            self.pair_relevance_score, "pair_relevance_score"
        )
        self.event_type = _require_non_empty_string(self.event_type, "event_type")
        if self.event_type not in EVENT_TYPES:
            raise SchemaValidationError(f"event_type must be one of {sorted(EVENT_TYPES)}")
        self.event_impact_score = _require_score(
            self.event_impact_score, "event_impact_score"
        )
        self.explanation = _require_non_empty_string(self.explanation, "explanation")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class MarketContext:
    pair: str
    timestamp: str
    rsi: float
    trend_score: float
    volatility_regime: str
    atr_percentile: float
    technical_alignment_score: float

    def __post_init__(self) -> None:
        self.pair = _require_pair(self.pair, "pair")
        self.timestamp = _require_iso8601_utc(self.timestamp, "timestamp")
        try:
            self.rsi = float(self.rsi)
        except (TypeError, ValueError):
            raise SchemaValidationError("rsi must be numeric") from None
        if self.rsi < 0.0 or self.rsi > 100.0:
            raise SchemaValidationError("rsi must be between 0 and 100")
        self.trend_score = _require_score(self.trend_score, "trend_score")
        self.volatility_regime = _require_non_empty_string(
            self.volatility_regime, "volatility_regime"
        )
        if self.volatility_regime not in VOLATILITY_REGIMES:
            raise SchemaValidationError(
                f"volatility_regime must be one of {sorted(VOLATILITY_REGIMES)}"
            )
        self.atr_percentile = _require_score(self.atr_percentile, "atr_percentile")
        self.technical_alignment_score = _require_score(
            self.technical_alignment_score, "technical_alignment_score"
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class SignalCandidate:
    signal_id: str
    pair: str
    direction: Literal["bullish", "bearish"]
    horizon: str
    confidence_raw: float
    confidence_calibrated: float
    thesis: str
    invalidation: str
    reasons: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        self.signal_id = _require_non_empty_string(self.signal_id, "signal_id")
        self.pair = _require_pair(self.pair, "pair")
        if self.direction not in {"bullish", "bearish"}:
            raise SchemaValidationError("direction must be bullish/bearish")
        self.horizon = _require_non_empty_string(self.horizon, "horizon")
        if self.horizon not in HORIZONS:
            raise SchemaValidationError(f"horizon must be one of {sorted(HORIZONS)}")
        self.confidence_raw = _require_score(self.confidence_raw, "confidence_raw")
        self.confidence_calibrated = _require_score(
            self.confidence_calibrated, "confidence_calibrated"
        )
        self.thesis = _require_non_empty_string(self.thesis, "thesis")
        self.invalidation = _require_non_empty_string(self.invalidation, "invalidation")

        if not isinstance(self.reasons, list):
            raise SchemaValidationError("reasons must be a list of strings")
        cleaned_reasons: list[str] = []
        for reason in self.reasons:
            cleaned_reasons.append(_require_non_empty_string(reason, "reasons[]"))
        self.reasons = cleaned_reasons

        if self.created_at:
            self.created_at = _require_iso8601_utc(self.created_at, "created_at")
        else:
            raise SchemaValidationError("created_at must be an ISO-8601 timestamp")

    def to_dict(self) -> dict:
        return asdict(self)
