from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
import math

from app.confidence_calibration import get_active_calibration_model
from app.impact_timing import ImpactTiming, evaluate_impact_timing
from app.schemas import MarketContext, PairImpact, SignalCandidate


Decision = Literal["publish", "hold", "reject"]

PUBLISH_THRESHOLD = 0.67
HOLD_THRESHOLD = 0.58
INTERCEPT = -1.85


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1 / (1 + z)
    z = math.exp(x)
    return z / (1 + z)


@dataclass(slots=True)
class ScoreInputs:
    pair_relevance: float
    event_impact: float
    sentiment_strength: float
    technical_alignment: float
    trend_score: float
    freshness: float
    source_reliability: float
    volatility_risk_penalty: float
    conflict_penalty: float


@dataclass(slots=True)
class SignalDecision:
    decision: Decision
    confidence_raw: float
    confidence_calibrated: float
    signal: SignalCandidate | None
    reasons: list[str]
    impact_timing: ImpactTiming | None = None


def compute_weighted_logit(inputs: ScoreInputs) -> float:
    return (
        INTERCEPT
        + 1.25 * _clamp01(inputs.pair_relevance)
        + 1.10 * _clamp01(inputs.event_impact)
        + 0.90 * _clamp01(inputs.sentiment_strength)
        + 1.00 * _clamp01(inputs.technical_alignment)
        + 0.60 * _clamp01(inputs.trend_score)
        + 0.40 * _clamp01(inputs.freshness)
        + 0.35 * _clamp01(inputs.source_reliability)
        - 0.55 * _clamp01(inputs.volatility_risk_penalty)
        - 0.50 * _clamp01(inputs.conflict_penalty)
    )


def calibrate_confidence(confidence_raw: float) -> float:
    # Conservative linear fallback when no fitted calibration model exists.
    baseline = _clamp01(0.92 * confidence_raw + 0.04)
    model = get_active_calibration_model()
    if model is None:
        return baseline
    return model.apply(confidence_raw)


def classify_decision(confidence_calibrated: float) -> Decision:
    if confidence_calibrated >= PUBLISH_THRESHOLD:
        return "publish"
    if confidence_calibrated >= HOLD_THRESHOLD:
        return "hold"
    return "reject"


def sentiment_strength_from_hint(direction_hint: str) -> float:
    if direction_hint in {"bullish", "bearish"}:
        return 0.75
    return 0.35


def volatility_penalty_from_regime(volatility_regime: str) -> float:
    if volatility_regime == "high":
        return 0.85
    if volatility_regime == "low":
        return 0.20
    return 0.35


def conflict_penalty(direction_hint: str, trend_score: float) -> float:
    if direction_hint == "bullish":
        return 0.10 if trend_score >= 0.5 else 0.70
    if direction_hint == "bearish":
        return 0.10 if trend_score <= 0.5 else 0.70
    return 0.20


def derive_direction(direction_hint: str, trend_score: float) -> str | None:
    if direction_hint in {"bullish", "bearish"}:
        return direction_hint
    if trend_score >= 0.55:
        return "bullish"
    if trend_score <= 0.45:
        return "bearish"
    return None


def apply_timing_gate(base_decision: Decision, impact_timing: ImpactTiming) -> Decision:
    if base_decision != "publish":
        return base_decision

    if impact_timing.impact_latency_class == "immediate":
        return "publish"
    if impact_timing.impact_latency_class == "short_lag":
        return "hold"
    return "reject"


def build_score_inputs(
    pair_impact: PairImpact,
    market_context: MarketContext,
    freshness: float = 0.70,
    source_reliability: float = 0.75,
) -> ScoreInputs:
    return ScoreInputs(
        pair_relevance=pair_impact.pair_relevance_score,
        event_impact=pair_impact.event_impact_score,
        sentiment_strength=sentiment_strength_from_hint(pair_impact.direction_hint),
        technical_alignment=market_context.technical_alignment_score,
        trend_score=market_context.trend_score,
        freshness=freshness,
        source_reliability=source_reliability,
        volatility_risk_penalty=volatility_penalty_from_regime(
            market_context.volatility_regime
        ),
        conflict_penalty=conflict_penalty(
            pair_impact.direction_hint, market_context.trend_score
        ),
    )


class WeightedSignalEngine:
    def __init__(
        self,
        publish_threshold: float = PUBLISH_THRESHOLD,
        hold_threshold: float = HOLD_THRESHOLD,
    ):
        self.publish_threshold = publish_threshold
        self.hold_threshold = hold_threshold

    def evaluate_pair(
        self,
        pair_impact: PairImpact,
        market_context: MarketContext,
        freshness: float = 0.70,
        source_reliability: float = 0.75,
        surprise_strength: float = 0.0,
    ) -> SignalDecision:
        score_inputs = build_score_inputs(
            pair_impact=pair_impact,
            market_context=market_context,
            freshness=freshness,
            source_reliability=source_reliability,
        )
        confidence_raw = _sigmoid(compute_weighted_logit(score_inputs))
        confidence_calibrated = calibrate_confidence(confidence_raw)

        base_decision = classify_decision(confidence_calibrated)
        impact_timing = evaluate_impact_timing(
            event_type=pair_impact.event_type,
            event_impact=pair_impact.event_impact_score,
            pair_relevance=pair_impact.pair_relevance_score,
            volatility_regime=market_context.volatility_regime,
            freshness=freshness,
            source_reliability=source_reliability,
            surprise_strength=surprise_strength,
            urgency_text=pair_impact.explanation,
        )
        decision = apply_timing_gate(base_decision, impact_timing)
        direction = derive_direction(pair_impact.direction_hint, market_context.trend_score)

        reasons = [
            f"event={pair_impact.event_type}",
            f"pair_relevance={pair_impact.pair_relevance_score:.2f}",
            f"technical_alignment={market_context.technical_alignment_score:.2f}",
            f"trend_score={market_context.trend_score:.2f}",
            f"impact_now={impact_timing.impact_now_score:.2f}",
            f"impact_latency={impact_timing.impact_latency_class}",
        ]

        if direction is None:
            return SignalDecision(
                decision="reject",
                confidence_raw=confidence_raw,
                confidence_calibrated=confidence_calibrated,
                signal=None,
                reasons=reasons + ["direction unresolved"],
                impact_timing=impact_timing,
            )

        signal = SignalCandidate(
            signal_id=f"sig_{pair_impact.pair.replace('/', '')}_{int(datetime.now(timezone.utc).timestamp())}",
            pair=pair_impact.pair,
            direction=direction,
            horizon="intraday",
            confidence_raw=confidence_raw,
            confidence_calibrated=confidence_calibrated,
            thesis=f"{pair_impact.event_type} signal with technical confirmation",
            invalidation="Invalidate if 1h candle closes against direction with weak momentum.",
            reasons=reasons,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

        return SignalDecision(
            decision=decision,
            confidence_raw=confidence_raw,
            confidence_calibrated=confidence_calibrated,
            signal=signal,
            reasons=reasons,
            impact_timing=impact_timing,
        )

    def evaluate_signals(
        self,
        pair_impacts: list[PairImpact],
        contexts: list[MarketContext],
        freshness: float = 0.70,
        source_reliability: float = 0.75,
        surprise_strength: float = 0.0,
        surprise_by_pair: dict[str, float] | None = None,
    ) -> list[SignalDecision]:
        context_map = {context.pair: context for context in contexts}
        decisions: list[SignalDecision] = []
        for pair_impact in pair_impacts:
            context = context_map.get(pair_impact.pair)
            if not context:
                continue
            pair_surprise = surprise_by_pair.get(pair_impact.pair, surprise_strength) if surprise_by_pair else surprise_strength
            decisions.append(
                self.evaluate_pair(
                    pair_impact=pair_impact,
                    market_context=context,
                    freshness=freshness,
                    source_reliability=source_reliability,
                    surprise_strength=pair_surprise,
                )
            )
        return decisions

    def generate_signals(
        self,
        pair_impacts: list[PairImpact],
        contexts: list[MarketContext],
    ) -> list[SignalCandidate]:
        published: list[SignalCandidate] = []
        for decision in self.evaluate_signals(pair_impacts, contexts):
            if decision.decision == "publish" and decision.signal is not None:
                published.append(decision.signal)
        return published
