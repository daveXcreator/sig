from __future__ import annotations

from collections import Counter
import re

from app.event_classifier import (
    classify_event_type,
    direction_hint_for_pair,
    score_event_impact,
)
from app.schemas import NormalizedArticle, PairImpact


MAJOR_PAIRS = (
    "EUR/USD",
    "USD/JPY",
    "GBP/USD",
    "USD/CHF",
    "AUD/USD",
    "USD/CAD",
    "NZD/USD",
)

PAIR_PATTERN = re.compile(r"\b([A-Z]{3}/[A-Z]{3})\b")

CURRENCY_ALIASES: dict[str, tuple[str, ...]] = {
    "USD": (
        "usd",
        "dollar",
        "u.s. dollar",
        "greenback",
        "fed",
        "federal reserve",
        "united states",
        "us economy",
    ),
    "EUR": ("eur", "euro", "ecb", "eurozone", "european central bank"),
    "JPY": ("jpy", "yen", "boj", "bank of japan", "japan"),
    "GBP": (
        "gbp",
        "pound",
        "sterling",
        "boe",
        "bank of england",
        "united kingdom",
        "uk",
        "britain",
    ),
    "CHF": ("chf", "swiss franc", "snb", "swiss national bank", "switzerland"),
    "AUD": ("aud", "aussie", "rba", "reserve bank of australia", "australia"),
    "CAD": ("cad", "loonie", "boc", "bank of canada", "canada"),
    "NZD": ("nzd", "kiwi", "rbnz", "reserve bank of new zealand", "new zealand"),
}

RISK_OFF_TERMS = (
    "risk off",
    "risk-off",
    "flight to safety",
    "safe haven",
    "volatility spike",
    "selloff",
    "escalation",
    "war",
    "attack",
    "bombing",
    "airstrike",
    "missile",
    "invasion",
    "sanction",
)

RISK_ON_TERMS = (
    "risk-on",
    "risk on",
    "ceasefire",
    "de-escalation",
    "talks resume",
    "truce",
    "peace talks",
)

RISK_OFF_PAIR_DIRECTION = {
    "EUR/USD": "bearish",
    "GBP/USD": "bearish",
    "AUD/USD": "bearish",
    "NZD/USD": "bearish",
    "USD/JPY": "bearish",
    "USD/CHF": "bearish",
    "USD/CAD": "bullish",
}


def _build_text(article: NormalizedArticle) -> str:
    return f"{article.title} {article.summary}".lower()


def _detect_explicit_pairs(text: str) -> list[str]:
    discovered: list[str] = []
    for pair in PAIR_PATTERN.findall(text.upper()):
        if pair in MAJOR_PAIRS and pair not in discovered:
            discovered.append(pair)
    return discovered


def _currency_mentions(text: str) -> Counter[str]:
    mentions: Counter[str] = Counter()
    for code, aliases in CURRENCY_ALIASES.items():
        count = 0
        for alias in aliases:
            count += len(re.findall(rf"\b{re.escape(alias)}\b", text))
        if count > 0:
            mentions[code] = count
    return mentions


def _pair_relevance(
    pair: str,
    explicit_pairs: list[str],
    mentions: Counter[str],
) -> float:
    if pair in explicit_pairs:
        return 0.95

    base, quote = pair.split("/")
    if base in mentions and quote in mentions:
        return 0.82

    if "USD" in (base, quote) and (base in mentions or quote in mentions):
        return 0.66

    return 0.52


def _risk_mode(text: str) -> str | None:
    risk_off_hits = sum(1 for term in RISK_OFF_TERMS if term in text)
    risk_on_hits = sum(1 for term in RISK_ON_TERMS if term in text)
    if risk_off_hits == 0 and risk_on_hits == 0:
        return None
    if risk_off_hits >= risk_on_hits:
        return "risk_off"
    return "risk_on"


def _apply_risk_direction_fallback(pair: str, event_type: str, text: str, current: str) -> str:
    if current in {"bullish", "bearish"}:
        return current
    if event_type not in {"geopolitical", "risk_sentiment"}:
        return current

    risk_mode = _risk_mode(text)
    if risk_mode is None:
        return current
    mapped = RISK_OFF_PAIR_DIRECTION.get(pair)
    if mapped is None:
        return current
    if risk_mode == "risk_off":
        return mapped
    return "bullish" if mapped == "bearish" else "bearish"


class DeterministicPairImpactExtractor:
    def extract_pair_impacts(self, article: NormalizedArticle) -> list[PairImpact]:
        text = _build_text(article)
        explicit_pairs = _detect_explicit_pairs(text)
        mentions = _currency_mentions(text)
        event_type = classify_event_type(text)
        primary_currency = mentions.most_common(1)[0][0] if mentions else None
        mention_strength = min(1.0, sum(mentions.values()) / 4.0) if mentions else 0.0

        candidate_pairs: list[str] = []

        for pair in explicit_pairs:
            if pair not in candidate_pairs:
                candidate_pairs.append(pair)

        for pair in MAJOR_PAIRS:
            base, quote = pair.split("/")
            if base in mentions and quote in mentions and pair not in candidate_pairs:
                candidate_pairs.append(pair)

        if not candidate_pairs and mentions:
            mapped = {
                "EUR": "EUR/USD",
                "JPY": "USD/JPY",
                "GBP": "GBP/USD",
                "CHF": "USD/CHF",
                "AUD": "AUD/USD",
                "CAD": "USD/CAD",
                "NZD": "NZD/USD",
            }
            for ccy, _count in mentions.most_common():
                if ccy in mapped and mapped[ccy] not in candidate_pairs:
                    candidate_pairs.append(mapped[ccy])
            candidate_pairs = candidate_pairs[:3]

        impacts: list[PairImpact] = []
        for pair in candidate_pairs[:4]:
            relevance = _pair_relevance(pair, explicit_pairs, mentions)
            direction = direction_hint_for_pair(pair, primary_currency, text)
            direction = _apply_risk_direction_fallback(
                pair=pair,
                event_type=event_type,
                text=text,
                current=direction,
            )
            impact_score = score_event_impact(
                event_type=event_type,
                text=text,
                has_explicit_pair=(pair in explicit_pairs),
                mention_strength=mention_strength,
            )

            explanation_bits = []
            if pair in explicit_pairs:
                explanation_bits.append("explicit pair mention")
            if primary_currency:
                explanation_bits.append(f"primary currency: {primary_currency}")
            explanation = ", ".join(explanation_bits) if explanation_bits else "entity mapping"

            impacts.append(
                PairImpact(
                    article_id=article.article_id,
                    pair=pair,
                    direction_hint=direction,
                    pair_relevance_score=relevance,
                    event_type=event_type,
                    event_impact_score=impact_score,
                    explanation=explanation,
                )
            )

        impacts.sort(key=lambda item: item.pair_relevance_score, reverse=True)
        return impacts
