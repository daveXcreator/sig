from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.schemas import MarketContext, NormalizedArticle, PairImpact, SignalCandidate
from app.strategy_config import MajorEventStrategyConfig


@dataclass(slots=True)
class PolicySelectionResult:
    signals: list[SignalCandidate]
    stats: dict[str, Any]


def _parse_iso8601_utc(value: str) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness_minutes(article: NormalizedArticle) -> float | None:
    published = _parse_iso8601_utc(article.published_at)
    fetched = _parse_iso8601_utc(article.fetched_at)
    if published is None or fetched is None:
        return None
    minutes = (fetched - published).total_seconds() / 60.0
    return max(0.0, minutes)


def _volatility_bucket(atr_percentile: float, strategy: MajorEventStrategyConfig) -> str:
    thresholds = strategy.raw["volatility_buckets"]
    low_max = float(thresholds["low_max_atr_percentile"])
    normal_max = float(thresholds["normal_max_atr_percentile"])
    if atr_percentile < low_max:
        return "low"
    if atr_percentile <= normal_max:
        return "normal"
    return "high"


def _is_event_allowed(pair_impact: PairImpact, strategy: MajorEventStrategyConfig) -> tuple[bool, bool]:
    universe = strategy.event_universe
    event_type = pair_impact.event_type
    if event_type in universe["primary"]:
        return True, False
    if event_type in universe["secondary"]:
        return True, True
    return False, False


def _passes_secondary_rules(
    pair_impact: PairImpact,
    impact_now_score: float | None,
    strategy: MajorEventStrategyConfig,
) -> bool:
    rules = strategy.event_universe["secondary_rules"]
    if pair_impact.event_impact_score < float(rules["event_impact_min"]):
        return False
    if pair_impact.pair_relevance_score < float(rules["pair_relevance_min"]):
        return False
    if impact_now_score is None:
        return False
    return impact_now_score >= float(rules["impact_now_min"])


def _passes_hard_gate(
    pair_impact: PairImpact,
    article: NormalizedArticle,
    impact_now_score: float | None,
    impact_latency_class: str | None,
    strategy: MajorEventStrategyConfig,
) -> tuple[bool, str | None]:
    gate = strategy.hard_gate
    if pair_impact.event_impact_score < float(gate["event_impact_min"]):
        return False, "event_impact"
    if pair_impact.pair_relevance_score < float(gate["pair_relevance_min"]):
        return False, "pair_relevance"
    if article.source_reliability < float(gate["source_reliability_min"]):
        return False, "source_reliability"

    freshness = _freshness_minutes(article)
    if freshness is None:
        return False, "freshness_missing"
    if freshness > float(gate["freshness_max_minutes"]):
        return False, "freshness_stale"

    if impact_now_score is None:
        return False, "impact_now_missing"
    if impact_now_score < float(gate["impact_now_min"]):
        return False, "impact_now"
    if not impact_latency_class:
        return False, "latency_missing"
    allowed_latency = set(gate["allowed_latency_classes"])
    if impact_latency_class not in allowed_latency:
        return False, "latency_class"

    return True, None


def _passes_bucket_thresholds(
    confidence: float,
    context: MarketContext,
    bucket: str,
    strategy: MajorEventStrategyConfig,
) -> bool:
    bucket_rules = strategy.publish_thresholds[bucket]
    if confidence < float(bucket_rules["confidence_min"]):
        return False
    if context.technical_alignment_score < float(bucket_rules["technical_alignment_min"]):
        return False
    return True


def _passes_trend_alignment(
    direction: str,
    context: MarketContext,
    strategy: MajorEventStrategyConfig,
) -> bool:
    trend = strategy.raw["trend_alignment"]
    bullish_min = float(trend["bullish_min_trend_score"])
    bearish_max = float(trend["bearish_max_trend_score"])
    if direction == "bullish":
        return context.trend_score >= bullish_min
    if direction == "bearish":
        return context.trend_score <= bearish_max
    return False


def select_publishable_signals_by_strategy(
    decisions: list[Any],
    pair_impacts: list[PairImpact],
    contexts: list[MarketContext],
    articles: list[NormalizedArticle],
    strategy: MajorEventStrategyConfig,
) -> PolicySelectionResult:
    impact_by_pair = {impact.pair: impact for impact in pair_impacts}
    context_by_pair = {context.pair: context for context in contexts}
    article_by_id = {article.article_id: article for article in articles}

    stats = {
        "considered": 0,
        "published": 0,
        "failed_event_universe": 0,
        "failed_secondary_rules": 0,
        "failed_hard_gate": 0,
        "failed_thresholds": 0,
        "failed_trend_alignment": 0,
        "failed_missing_context": 0,
        "failed_hard_gate_breakdown": {},
    }
    selected: list[SignalCandidate] = []

    for decision in decisions:
        if getattr(decision, "decision", "") != "publish":
            continue
        signal = getattr(decision, "signal", None)
        if signal is None:
            continue

        stats["considered"] += 1

        pair_impact = impact_by_pair.get(signal.pair)
        context = context_by_pair.get(signal.pair)
        if pair_impact is None or context is None:
            stats["failed_missing_context"] += 1
            continue

        article = article_by_id.get(pair_impact.article_id)
        if article is None:
            stats["failed_missing_context"] += 1
            continue

        impact_timing = getattr(decision, "impact_timing", None)
        impact_now_score = (
            float(getattr(impact_timing, "impact_now_score", 0.0))
            if impact_timing is not None
            else None
        )
        impact_latency_class = (
            str(getattr(impact_timing, "impact_latency_class", ""))
            if impact_timing is not None
            else None
        )

        allowed, secondary = _is_event_allowed(pair_impact, strategy)
        if not allowed:
            stats["failed_event_universe"] += 1
            continue
        if secondary and not _passes_secondary_rules(pair_impact, impact_now_score, strategy):
            stats["failed_secondary_rules"] += 1
            continue

        hard_gate_passed, hard_gate_reason = _passes_hard_gate(
            pair_impact=pair_impact,
            article=article,
            impact_now_score=impact_now_score,
            impact_latency_class=impact_latency_class,
            strategy=strategy,
        )
        if not hard_gate_passed:
            stats["failed_hard_gate"] += 1
            if hard_gate_reason:
                breakdown = stats.setdefault("failed_hard_gate_breakdown", {})
                breakdown[hard_gate_reason] = int(breakdown.get(hard_gate_reason, 0)) + 1
            continue

        bucket = _volatility_bucket(context.atr_percentile, strategy)
        confidence = float(getattr(decision, "confidence_calibrated", signal.confidence_calibrated))
        if not _passes_bucket_thresholds(confidence=confidence, context=context, bucket=bucket, strategy=strategy):
            stats["failed_thresholds"] += 1
            continue

        if not _passes_trend_alignment(direction=signal.direction, context=context, strategy=strategy):
            stats["failed_trend_alignment"] += 1
            continue

        selected.append(signal)
        stats["published"] += 1

    return PolicySelectionResult(signals=selected, stats=stats)
