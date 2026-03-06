from __future__ import annotations

import re

from app.schemas import SchemaValidationError


EVENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "rate_decision": (
        "rate hike",
        "rate cut",
        "interest rate",
        "policy rate",
        "policy decision",
        "tightening",
        "easing",
        "hawkish",
        "dovish",
        "central bank",
        "federal reserve",
        "fed",
        "fomc",
        "ecb",
        "boe",
        "boj",
        "snb",
        "rba",
        "boc",
        "rbnz",
    ),
    "inflation": (
        "inflation",
        "cpi",
        "ppi",
        "price pressures",
        "core cpi",
        "headline inflation",
        "consumer prices",
        "disinflation",
    ),
    "employment": (
        "jobs",
        "jobless",
        "payroll",
        "nonfarm payroll",
        "unemployment",
        "labor market",
        "wage growth",
        "employment report",
        "nfp",
    ),
    "geopolitical": (
        "war",
        "conflict",
        "tariff",
        "sanction",
        "embargo",
        "election",
        "attack",
        "bombing",
        "airstrike",
        "drone strike",
        "missile",
        "invasion",
        "military",
        "ceasefire",
        "state of emergency",
    ),
    "risk_sentiment": (
        "risk-on",
        "risk off",
        "risk-off",
        "safe haven",
        "equity selloff",
        "stock selloff",
        "risk appetite",
        "market sentiment",
        "flight to safety",
        "volatility spike",
        "vix",
        "yield surge",
        "oil spike",
    ),
}

EVENT_BASE_IMPACT: dict[str, float] = {
    "rate_decision": 0.72,
    "inflation": 0.68,
    "employment": 0.64,
    "geopolitical": 0.70,
    "risk_sentiment": 0.60,
    "other": 0.45,
}

BULLISH_HINTS = (
    "rally",
    "gains",
    "strengthens",
    "surges",
    "jumps",
    "hawkish",
    "higher",
    "beats estimates",
)

BEARISH_HINTS = (
    "falls",
    "drops",
    "weakens",
    "slumps",
    "dovish",
    "lower",
    "selloff",
    "misses estimates",
)


def classify_event_type(text: str) -> str:
    lowered = (text or "").lower()
    for event_type, keywords in EVENT_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return event_type
    return "other"


def sentiment_direction(text: str) -> int:
    lowered = (text or "").lower()
    bullish = sum(lowered.count(token) for token in BULLISH_HINTS)
    bearish = sum(lowered.count(token) for token in BEARISH_HINTS)
    if bullish > bearish:
        return 1
    if bearish > bullish:
        return -1
    return 0


def sentiment_strength(text: str) -> float:
    lowered = (text or "").lower()
    bullish = sum(lowered.count(token) for token in BULLISH_HINTS)
    bearish = sum(lowered.count(token) for token in BEARISH_HINTS)
    total = bullish + bearish
    if total == 0:
        return 0.0
    imbalance = abs(bullish - bearish)
    return min(1.0, 0.25 + (imbalance / total) * 0.75)


def score_event_impact(
    event_type: str,
    text: str,
    has_explicit_pair: bool,
    mention_strength: float,
) -> float:
    if event_type not in EVENT_BASE_IMPACT:
        raise SchemaValidationError("Unknown event_type for impact scoring")

    score = EVENT_BASE_IMPACT[event_type]
    score += 0.14 * sentiment_strength(text)
    score += 0.09 if has_explicit_pair else 0.0
    score += 0.07 * max(0.0, min(mention_strength, 1.0))

    return max(0.0, min(score, 1.0))


def direction_hint_for_pair(
    pair: str,
    primary_currency: str | None,
    text: str,
) -> str:
    direction = sentiment_direction(text)
    if direction == 0 or not primary_currency:
        return "neutral"

    if not re.match(r"^[A-Z]{3}/[A-Z]{3}$", pair):
        raise SchemaValidationError("pair must match AAA/BBB")

    base, quote = pair.split("/")
    if primary_currency == base:
        return "bullish" if direction > 0 else "bearish"
    if primary_currency == quote:
        return "bearish" if direction > 0 else "bullish"
    return "neutral"
