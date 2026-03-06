from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ImpactLatencyClass = Literal["immediate", "short_lag", "slow_burn"]


EVENT_IMMEDIACY_BASE = {
    "rate_decision": 0.90,
    "inflation": 0.84,
    "employment": 0.80,
    "geopolitical": 0.88,
    "risk_sentiment": 0.72,
    "other": 0.45,
}

VOLATILITY_IMMEDIACY = {
    "high": 0.90,
    "normal": 0.62,
    "low": 0.35,
}

URGENCY_TERMS = (
    "breaking",
    "unexpected",
    "surprise",
    "emergency",
    "shock",
    "urgent",
)


@dataclass(slots=True)
class ImpactTiming:
    impact_latency_class: ImpactLatencyClass
    impact_now_score: float
    activation_window: str
    expires_in_minutes: int


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _urgency_bonus(text: str) -> float:
    lowered = (text or "").lower()
    hits = sum(1 for term in URGENCY_TERMS if term in lowered)
    return min(0.08, 0.02 * hits)


def estimate_impact_now_score(
    event_type: str,
    event_impact: float,
    pair_relevance: float,
    volatility_regime: str,
    freshness: float,
    source_reliability: float,
    surprise_strength: float = 0.0,
    urgency_text: str = "",
) -> float:
    event_base = EVENT_IMMEDIACY_BASE.get(event_type, EVENT_IMMEDIACY_BASE["other"])
    volatility_component = VOLATILITY_IMMEDIACY.get(
        volatility_regime, VOLATILITY_IMMEDIACY["normal"]
    )

    score = (
        0.30 * event_base
        + 0.22 * _clamp01(event_impact)
        + 0.16 * _clamp01(pair_relevance)
        + 0.10 * _clamp01(freshness)
        + 0.08 * _clamp01(source_reliability)
        + 0.08 * _clamp01(volatility_component)
        + 0.06 * _clamp01(surprise_strength)
        + _urgency_bonus(urgency_text)
    )
    return _clamp01(score)


def classify_latency(impact_now_score: float) -> ImpactLatencyClass:
    score = _clamp01(impact_now_score)
    if score >= 0.75:
        return "immediate"
    if score >= 0.55:
        return "short_lag"
    return "slow_burn"


def activation_window_for_latency(latency: ImpactLatencyClass) -> tuple[str, int]:
    if latency == "immediate":
        return "now-30m", 90
    if latency == "short_lag":
        return "1-4h", 360
    return "4-24h", 1440


def evaluate_impact_timing(
    event_type: str,
    event_impact: float,
    pair_relevance: float,
    volatility_regime: str,
    freshness: float,
    source_reliability: float,
    surprise_strength: float = 0.0,
    urgency_text: str = "",
) -> ImpactTiming:
    impact_now_score = estimate_impact_now_score(
        event_type=event_type,
        event_impact=event_impact,
        pair_relevance=pair_relevance,
        volatility_regime=volatility_regime,
        freshness=freshness,
        source_reliability=source_reliability,
        surprise_strength=surprise_strength,
        urgency_text=urgency_text,
    )
    latency = classify_latency(impact_now_score)
    activation_window, expires_in_minutes = activation_window_for_latency(latency)
    return ImpactTiming(
        impact_latency_class=latency,
        impact_now_score=impact_now_score,
        activation_window=activation_window,
        expires_in_minutes=expires_in_minutes,
    )
