from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from app.config import (
    ENABLE_ECONOMIC_CALENDAR,
    ENABLE_FILE_ROLLBACK_SWITCH,
    ENABLE_PUBLIC_POSTING,
    MAX_EXTRACTION_ARTICLES,
    MAX_PUBLISHABLE_SIGNALS_PER_RUN,
    OPENAI_API_KEY,
    REQUIRE_MAJOR_EVENT_FILTER,
    ROLLBACK_SWITCH_FILE,
    ROLLBACK_SWITCH_ACTIVE,
)
from app.economic_calendar import FmpEconomicCalendarClient, pair_surprise_strength
from app.dry_run_pipeline import normalize_articles
from app.entity_pair_extractor import DeterministicPairImpactExtractor
from app.event_classifier import classify_event_type, score_event_impact
from app.market_context import AlphaVantageMarketContextProvider
from app.major_event_policy import select_publishable_signals_by_strategy
from app.news_fetcher import fetch_forex_news
from app.pair_detector import detect_currency_pairs
from app.publisher import PublisherConfig, SignalPublisher
from app.run_history_store import append_run_history
from app.signal_setup import AlphaVantageIntradayProvider, build_execution_plans
from app.schemas import PairImpact, SignalCandidate
from app.sentiment_analyzer import analyze_sentiment
from app.signal_engine import WeightedSignalEngine
from app.strategy_config import StrategyConfigError, load_major_event_strategy
from app.trade_tracker import TradeTracker
from app.utils import generate_run_id, log, log_event

TRADABLE_PAIRS = {
    "EUR/USD",
    "USD/JPY",
    "GBP/USD",
    "USD/CHF",
    "AUD/USD",
    "USD/CAD",
    "NZD/USD",
}
MAJOR_EVENT_TYPES = {
    "rate_decision",
    "inflation",
    "employment",
    "geopolitical",
    "risk_sentiment",
}
MAJOR_EVENT_KEYWORDS = {
    "rate",
    "rates",
    "fomc",
    "ecb",
    "boe",
    "boj",
    "fed",
    "inflation",
    "cpi",
    "ppi",
    "employment",
    "jobs",
    "nfp",
    "payroll",
    "unemployment",
    "geopolitical",
    "sanction",
    "sanctions",
    "conflict",
    "war",
    "tariff",
    "tariffs",
    "risk-off",
    "risk on",
    "risk-on",
}
TRADABLE_TOKEN_HINTS = {
    "usd",
    "dollar",
    "euro",
    "eur",
    "yen",
    "jpy",
    "pound",
    "sterling",
    "gbp",
    "aussie",
    "aud",
    "cad",
    "loonie",
    "nzd",
    "kiwi",
    "chf",
    "franc",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_publish_guardrail(publish_enabled: bool) -> tuple[bool, str | None, bool]:
    if not publish_enabled:
        return False, "publish_disabled_runtime", False
    if not ENABLE_PUBLIC_POSTING:
        return False, "publish_disabled_env", False
    if ROLLBACK_SWITCH_ACTIVE:
        return False, "rollback_switch_active_env", True
    rollback_switch = Path(ROLLBACK_SWITCH_FILE)
    if ENABLE_FILE_ROLLBACK_SWITCH and rollback_switch.exists():
        return False, "rollback_switch_active", True
    return True, None, False


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _contains_major_event_keywords(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in MAJOR_EVENT_KEYWORDS)


def _contains_tradable_pair_mention(text: str) -> bool:
    lowered = text.lower()
    for pair in TRADABLE_PAIRS:
        normalized = pair.lower()
        compact = normalized.replace("/", "")
        if normalized in lowered or compact in lowered:
            return True
    return False


def _tradable_token_score(text: str) -> int:
    lowered = text.lower()
    score = 0
    for token in TRADABLE_TOKEN_HINTS:
        if token in lowered:
            score += 1
    return score


def _article_extraction_score(article: Any) -> float:
    text = f"{getattr(article, 'title', '')} {getattr(article, 'summary', '')}".strip()
    major = _contains_major_event_keywords(text)
    pair_mention = _contains_tradable_pair_mention(text)
    token_score = _tradable_token_score(text)
    reliability = float(getattr(article, "source_reliability", 0.6))
    event_weight = 2.5 if major else 0.0
    pair_weight = 3.0 if pair_mention else 0.0
    lexical_weight = min(float(token_score) * 0.35, 2.1)
    return pair_weight + event_weight + lexical_weight + reliability


def _select_articles_for_extraction(articles: list[Any]) -> tuple[list[Any], int]:
    if not articles:
        return [], 0

    candidates: list[Any] = []
    for article in articles:
        text = f"{getattr(article, 'title', '')} {getattr(article, 'summary', '')}".strip()
        has_pair = _contains_tradable_pair_mention(text)
        has_major = _contains_major_event_keywords(text)
        has_tradable_context = _tradable_token_score(text) > 0

        if has_pair:
            candidates.append(article)
            continue

        if REQUIRE_MAJOR_EVENT_FILTER:
            if has_major and has_tradable_context:
                candidates.append(article)
            continue

        if has_major or has_tradable_context:
            candidates.append(article)

    ranked = sorted(
        candidates,
        key=_article_extraction_score,
        reverse=True,
    )
    cap = max(1, int(MAX_EXTRACTION_ARTICLES))
    selected = ranked[:cap]
    skipped = max(0, len(articles) - len(selected))
    return selected, skipped


def _best_pair_impacts_by_pair(impacts: list[PairImpact]) -> list[PairImpact]:
    best: dict[str, PairImpact] = {}
    for impact in impacts:
        if impact.pair not in TRADABLE_PAIRS:
            continue
        existing = best.get(impact.pair)
        candidate_score = impact.pair_relevance_score * impact.event_impact_score
        if existing is None:
            best[impact.pair] = impact
            continue
        existing_score = existing.pair_relevance_score * existing.event_impact_score
        if candidate_score > existing_score:
            best[impact.pair] = impact
    return list(best.values())


def _drop_counts_by_stage(details: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in details:
        stage = str(item.get("stage", "")).strip()
        if not stage:
            continue
        counts[stage] = counts.get(stage, 0) + 1
    return counts


def _merge_openai_with_deterministic(
    title: str,
    summary: str,
    openai_pairs: list[str],
    sentiment_items: list[dict[str, Any]],
    deterministic_impacts: list[PairImpact],
    article_id: str,
) -> list[PairImpact]:
    text = f"{title} {summary}".lower()
    deterministic_map = {impact.pair: impact for impact in deterministic_impacts}
    event_type = classify_event_type(text)

    merged: list[PairImpact] = []
    seen: set[str] = set()

    sentiment_map = {item.get("pair"): item for item in sentiment_items if item.get("pair")}

    for pair in openai_pairs:
        seen.add(pair)
        deterministic = deterministic_map.get(pair)
        sentiment = sentiment_map.get(pair)

        confidence = _clamp01(sentiment.get("confidence", 0.55) if sentiment else 0.55)
        direction_hint = sentiment.get("sentiment", "neutral") if sentiment else (
            deterministic.direction_hint if deterministic else "neutral"
        )
        if direction_hint not in {"bullish", "bearish", "neutral"}:
            direction_hint = "neutral"

        base_relevance = deterministic.pair_relevance_score if deterministic else 0.60
        pair_relevance = _clamp01(max(base_relevance, 0.40 + 0.55 * confidence))

        derived_event_type = deterministic.event_type if deterministic else event_type
        derived_event_impact = (
            deterministic.event_impact_score
            if deterministic
            else score_event_impact(
                event_type=derived_event_type,
                text=text,
                has_explicit_pair=(pair in openai_pairs),
                mention_strength=confidence,
            )
        )

        explanation = (
            f"openai_confidence={confidence:.2f}; "
            f"{deterministic.explanation if deterministic else 'openai_pair_mapping'}"
        )
        merged.append(
            PairImpact(
                article_id=article_id,
                pair=pair,
                direction_hint=direction_hint,
                pair_relevance_score=pair_relevance,
                event_type=derived_event_type,
                event_impact_score=_clamp01(derived_event_impact),
                explanation=explanation,
            )
        )

    # Keep deterministic-only pairs as low-priority candidates when OpenAI misses them.
    for impact in deterministic_impacts:
        if impact.pair in seen:
            continue
        merged.append(impact)

    return merged


def run_live_v2(enable_x: bool = False, publish_enabled: bool = True) -> dict[str, Any]:
    run_id = generate_run_id("livev2")
    started_at = time.perf_counter()
    stage_latency_ms: dict[str, float] = {}
    run_metrics: dict[str, int] = {
        "articles_fetched": 0,
        "articles_normalized": 0,
        "articles_selected_for_extraction": 0,
        "articles_skipped_before_openai": 0,
        "pair_impacts_generated": 0,
        "market_contexts_generated": 0,
        "calendar_events": 0,
        "decisions_generated": 0,
        "signals_policy_selected": 0,
        "execution_plans_built": 0,
        "signals_with_plan": 0,
        "publish_candidates": 0,
        "publish_capped_dropped": 0,
        "publishing_skipped": 0,
        "trade_results_generated": 0,
        "tracked_trades_new": 0,
        "tracked_trades_active": 0,
    }
    coverage_metrics: dict[str, Any] = {
        "raw_articles": 0,
        "raw_unique_titles": 0,
        "major_event_articles": 0,
        "major_event_impacts": 0,
        "major_event_decisions": 0,
        "source_counts": {},
    }
    signal_drop_details: list[dict[str, Any]] = []

    def complete_stage(stage: str, stage_started_at: float, result: str = "ok", **fields: Any) -> None:
        latency = (time.perf_counter() - stage_started_at) * 1000
        stage_latency_ms[stage] = round(latency, 2)
        log_event(
            stage=stage,
            event="completed",
            run_id=run_id,
            latency_ms=latency,
            result=result,
            **fields,
        )

    def finalize(summary: dict[str, Any], result: str | None = None) -> dict[str, Any]:
        total_latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        summary["finished_at"] = _utc_now_iso()
        summary["run_id"] = run_id
        summary["stage_latency_ms"] = stage_latency_ms
        summary["total_latency_ms"] = total_latency_ms
        summary["run_metrics"] = run_metrics
        summary["coverage_metrics"] = coverage_metrics
        log_event(
            stage="pipeline",
            event="finished",
            run_id=run_id,
            latency_ms=total_latency_ms,
            result=result or summary.get("status", "ok"),
            reason=summary.get("reason"),
            publishable_signals=summary.get("publishable_signals"),
            major_event_articles=coverage_metrics.get("major_event_articles", 0),
            major_event_impacts=coverage_metrics.get("major_event_impacts", 0),
        )
        try:
            append_run_history(summary)
        except Exception as err:
            log(f"Run history write failed: {err}")
        log(f"Live V2 summary: {summary}")
        return summary

    log_event(
        stage="pipeline",
        event="started",
        run_id=run_id,
        result="started",
        enable_x=enable_x,
        publish_enabled=publish_enabled,
    )

    if not OPENAI_API_KEY:
        log("OPENAI_API_KEY is required for live V2 pipeline.")
        log_event(
            stage="config",
            event="validation_failed",
            run_id=run_id,
            result="failed",
            reason="missing_openai_key",
        )
        return finalize({"status": "failed", "reason": "missing_openai_key"}, result="failed")

    ingestion_started = time.perf_counter()
    raw_articles = fetch_forex_news()
    run_metrics["articles_fetched"] = len(raw_articles)
    coverage_metrics["raw_articles"] = len(raw_articles)
    coverage_metrics["raw_unique_titles"] = len(
        {str(item.get("title", "")).strip().lower() for item in raw_articles if item.get("title")}
    )
    source_counts: dict[str, int] = {}
    for item in raw_articles:
        source = str(item.get("source", "Unknown")).strip() or "Unknown"
        source_counts[source] = source_counts.get(source, 0) + 1
    coverage_metrics["source_counts"] = source_counts
    complete_stage(
        "ingestion",
        ingestion_started,
        result="ok" if raw_articles else "empty",
        articles_fetched=len(raw_articles),
        raw_unique_titles=coverage_metrics["raw_unique_titles"],
    )
    if not raw_articles:
        log("No news available for live V2 pipeline.")
        return finalize({"status": "ok", "published": 0, "reason": "no_news"})

    normalization_started = time.perf_counter()
    articles = normalize_articles(raw_articles)
    run_metrics["articles_normalized"] = len(articles)
    coverage_metrics["major_event_articles"] = sum(
        1
        for article in articles
        if classify_event_type(f"{article.title} {article.summary}") in MAJOR_EVENT_TYPES
    )
    complete_stage(
        "normalization",
        normalization_started,
        result="ok" if articles else "empty",
        articles_normalized=len(articles),
        major_event_articles=coverage_metrics["major_event_articles"],
    )
    if not articles:
        log("No normalized articles after preprocessing.")
        return finalize({"status": "ok", "published": 0, "reason": "no_normalized_articles"})

    extraction_articles, skipped_before_openai = _select_articles_for_extraction(articles)
    run_metrics["articles_selected_for_extraction"] = len(extraction_articles)
    run_metrics["articles_skipped_before_openai"] = skipped_before_openai
    if not extraction_articles:
        log("No extraction candidates after major-event/tradable prefilter.")
        return finalize({"status": "ok", "published": 0, "reason": "no_extraction_candidates"})

    extraction_started = time.perf_counter()
    extractor = DeterministicPairImpactExtractor()
    all_impacts: list[PairImpact] = []

    for article in extraction_articles:
        deterministic_impacts = extractor.extract_pair_impacts(article)
        deterministic_impacts = [
            impact for impact in deterministic_impacts if impact.pair in TRADABLE_PAIRS
        ]

        openai_pairs = detect_currency_pairs(
            article.title,
            article.summary,
            allowed_pairs=sorted(TRADABLE_PAIRS),
        )
        openai_pairs = [pair for pair in openai_pairs if pair in TRADABLE_PAIRS]
        if not openai_pairs:
            # OpenAI is required, but deterministic fallback avoids hard stop on one bad call.
            all_impacts.extend(deterministic_impacts)
            continue

        sentiment_items = analyze_sentiment(article.title, article.summary, openai_pairs)
        merged = _merge_openai_with_deterministic(
            title=article.title,
            summary=article.summary,
            openai_pairs=openai_pairs,
            sentiment_items=sentiment_items,
            deterministic_impacts=deterministic_impacts,
            article_id=article.article_id,
        )
        all_impacts.extend(merged)

    impacts = _best_pair_impacts_by_pair(all_impacts)
    run_metrics["pair_impacts_generated"] = len(impacts)
    coverage_metrics["major_event_impacts"] = sum(
        1 for impact in impacts if impact.event_type in MAJOR_EVENT_TYPES
    )
    complete_stage(
        "pair_impact",
        extraction_started,
        result="ok" if impacts else "empty",
        pair_impacts_generated=len(impacts),
        major_event_impacts=coverage_metrics["major_event_impacts"],
        extraction_articles_selected=len(extraction_articles),
        extraction_articles_skipped=skipped_before_openai,
    )
    if not impacts:
        log("No pair impacts generated.")
        return finalize({"status": "ok", "published": 0, "reason": "no_impacts"})

    context_started = time.perf_counter()
    context_provider = AlphaVantageMarketContextProvider()
    contexts = context_provider.build_context([impact.pair for impact in impacts])
    run_metrics["market_contexts_generated"] = len(contexts)
    complete_stage(
        "market_context",
        context_started,
        result="ok" if contexts else "empty",
        contexts_generated=len(contexts),
    )
    if not contexts:
        log("No market contexts generated.")
        return finalize({"status": "ok", "published": 0, "reason": "no_context"})

    calendar_started = time.perf_counter()
    calendar_events = []
    if ENABLE_ECONOMIC_CALENDAR:
        calendar_client = FmpEconomicCalendarClient()
        calendar_events = calendar_client.fetch_recent_window(days_back=1, days_forward=1)
    else:
        log("Economic calendar integration disabled by config.")
    run_metrics["calendar_events"] = len(calendar_events)
    complete_stage(
        "calendar",
        calendar_started,
        result="ok" if ENABLE_ECONOMIC_CALENDAR else "disabled",
        calendar_events=len(calendar_events),
    )

    decision_started = time.perf_counter()
    surprise_by_pair = pair_surprise_strength(
        events=calendar_events,
        pairs=[impact.pair for impact in impacts],
    )

    engine = WeightedSignalEngine()
    decisions = engine.evaluate_signals(
        impacts,
        contexts,
        surprise_by_pair=surprise_by_pair,
    )
    run_metrics["decisions_generated"] = len(decisions)
    impact_by_pair = {impact.pair: impact for impact in impacts}
    coverage_metrics["major_event_decisions"] = sum(
        1
        for decision in decisions
        if getattr(decision, "signal", None) is not None
        and (
            (impact_by_pair.get(decision.signal.pair).event_type in MAJOR_EVENT_TYPES)
            if impact_by_pair.get(decision.signal.pair) is not None
            else False
        )
    )
    complete_stage(
        "decision",
        decision_started,
        result="ok",
        decisions_generated=len(decisions),
        major_event_decisions=coverage_metrics["major_event_decisions"],
    )

    for decision in decisions:
        signal = getattr(decision, "signal", None)
        if signal is None:
            continue
        decision_result = str(getattr(decision, "decision", "unknown"))
        event_started = time.perf_counter()
        log_event(
            stage="decision",
            event="signal_decision",
            run_id=run_id,
            signal_id=signal.signal_id,
            latency_ms=(time.perf_counter() - event_started) * 1000,
            result=decision_result,
            pair=signal.pair,
            direction=signal.direction,
        )
        if decision_result != "publish":
            signal_drop_details.append(
                {
                    "stage": "signal_decision",
                    "reason": f"engine_{decision_result}",
                    "signal_id": signal.signal_id,
                    "pair": signal.pair,
                    "direction": signal.direction,
                }
            )

    strategy_started = time.perf_counter()
    try:
        strategy = load_major_event_strategy()
    except StrategyConfigError as err:
        complete_stage(
            "strategy",
            strategy_started,
            result="failed",
            reason="invalid_strategy_config",
        )
        log(f"Strategy config load failed: {err}")
        return finalize({"status": "failed", "reason": "invalid_strategy_config"}, result="failed")
    complete_stage("strategy", strategy_started, result="ok")

    policy_started = time.perf_counter()
    policy_result = select_publishable_signals_by_strategy(
        decisions=decisions,
        pair_impacts=impacts,
        contexts=contexts,
        articles=articles,
        strategy=strategy,
    )
    publishable = policy_result.signals
    signal_drop_details.extend(policy_result.drop_details)
    run_metrics["signals_policy_selected"] = len(publishable)
    complete_stage(
        "policy",
        policy_started,
        result="ok",
        signals_policy_selected=len(publishable),
    )

    execution_started = time.perf_counter()
    intraday_provider = AlphaVantageIntradayProvider()
    execution_plans = build_execution_plans(
        signals=publishable,
        strategy=strategy,
        intraday_provider=intraday_provider,
    )
    run_metrics["execution_plans_built"] = len(execution_plans)
    run_metrics["signals_with_plan"] = len(
        [signal for signal in publishable if signal.signal_id in execution_plans]
    )
    complete_stage(
        "execution_plan",
        execution_started,
        result="ok",
        execution_plans_built=len(execution_plans),
    )

    for signal in publishable:
        signal_started = time.perf_counter()
        has_plan = signal.signal_id in execution_plans
        log_event(
            stage="execution_plan",
            event="signal_plan",
            run_id=run_id,
            signal_id=signal.signal_id,
            latency_ms=(time.perf_counter() - signal_started) * 1000,
            result="planned" if has_plan else "dropped",
            pair=signal.pair,
        )
        if not has_plan:
            signal_drop_details.append(
                {
                    "stage": "execution_plan",
                    "reason": "missing_execution_plan",
                    "signal_id": signal.signal_id,
                    "pair": signal.pair,
                    "direction": signal.direction,
                }
            )

    publish_candidates = [signal for signal in publishable if signal.signal_id in execution_plans]
    run_metrics["publish_candidates"] = len(publish_candidates)

    decision_confidence = {
        decision.signal.signal_id: float(getattr(decision, "confidence_calibrated", 0.0))
        for decision in decisions
        if getattr(decision, "signal", None) is not None
    }
    publishable = publish_candidates
    cap = int(MAX_PUBLISHABLE_SIGNALS_PER_RUN)
    dropped_by_cap: list[SignalCandidate] = []
    if cap > 0 and len(publishable) > cap:
        ranked_candidates = sorted(
            publishable,
            key=lambda signal: (
                decision_confidence.get(signal.signal_id, signal.confidence_calibrated),
                signal.confidence_calibrated,
            ),
            reverse=True,
        )
        publishable = ranked_candidates[:cap]
        dropped_by_cap = ranked_candidates[cap:]
    run_metrics["publish_capped_dropped"] = len(publish_candidates) - len(publishable)
    for signal in dropped_by_cap:
        signal_drop_details.append(
            {
                "stage": "publish_cap",
                "reason": "max_publishable_signals_per_run",
                "signal_id": signal.signal_id,
                "pair": signal.pair,
                "direction": signal.direction,
            }
        )

    tracking_started = time.perf_counter()
    trade_tracker = TradeTracker()
    trade_result_updates = trade_tracker.evaluate_open_trades(intraday_provider=intraday_provider)
    tracked_new = trade_tracker.register_new_plans(execution_plans)
    run_metrics["trade_results_generated"] = len(trade_result_updates)
    run_metrics["tracked_trades_new"] = tracked_new
    run_metrics["tracked_trades_active"] = trade_tracker.count_active()
    complete_stage(
        "tracking",
        tracking_started,
        result="ok",
        trade_results_generated=len(trade_result_updates),
        tracked_trades_new=tracked_new,
    )

    publish_started = time.perf_counter()
    can_publish, publish_guardrail_reason, rollback_active = _resolve_publish_guardrail(
        publish_enabled=publish_enabled
    )
    result_stats = {"telegram": 0, "x": 0}
    telegram_stats = {
        "telegram": 0,
        "x": 0,
        "news_briefs": 0,
        "verdicts": 0,
        "signal_alerts": 0,
        "images": 0,
    }
    x_count = 0

    if can_publish:
        telegram_publisher = SignalPublisher(
            PublisherConfig(enable_telegram=True, enable_x=False, include_disclaimer=True)
        )
        result_stats = telegram_publisher.publish_trade_result_updates(trade_result_updates)
        telegram_stats = telegram_publisher.publish_market_narrative(
            articles=articles,
            impacts=impacts,
            contexts=contexts,
            decisions=decisions,
            signals=publishable,
            execution_plans=execution_plans,
        )

        if enable_x:
            x_publisher = SignalPublisher(
                PublisherConfig(enable_telegram=False, enable_x=True, include_disclaimer=True)
            )
            x_stats = x_publisher.publish_signals(publishable)
            x_count = x_stats.get("x", 0)
    else:
        run_metrics["publishing_skipped"] = 1
        log(f"Publishing skipped by guardrail ({publish_guardrail_reason}).")
        for signal in publishable:
            signal_drop_details.append(
                {
                    "stage": "publishing_guardrail",
                    "reason": publish_guardrail_reason or "guardrail",
                    "signal_id": signal.signal_id,
                    "pair": signal.pair,
                    "direction": signal.direction,
                }
            )

    complete_stage(
        "publishing",
        publish_started,
        result="ok" if can_publish else "skipped",
        reason=publish_guardrail_reason,
        telegram_posts=telegram_stats.get("telegram", 0),
        images_published=telegram_stats.get("images", 0),
        x_posts=x_count,
    )

    publish_stats = {
        "telegram": telegram_stats.get("telegram", 0),
        "x": x_count,
        "results": result_stats.get("telegram", 0),
    }

    summary = {
        "status": "ok",
        "articles": len(articles),
        "impacts": len(impacts),
        "contexts": len(contexts),
        "decisions": len(decisions),
        "publishable_signals": len(publishable),
        "publish_candidate_signals": len(publish_candidates),
        "publish_stats": publish_stats,
        "news_briefs_published": telegram_stats.get("news_briefs", 0),
        "verdicts_published": telegram_stats.get("verdicts", 0),
        "signal_alerts_published": telegram_stats.get("signal_alerts", len(publishable)),
        "images_published": telegram_stats.get("images", 0),
        "publishing_enabled": can_publish,
        "publish_guardrail_reason": publish_guardrail_reason,
        "rollback_switch_active": rollback_active,
        "publish_cap": cap,
        "publish_capped_dropped": run_metrics["publish_capped_dropped"],
        "policy_considered": policy_result.stats.get("considered", 0),
        "policy_published": policy_result.stats.get("published", 0),
        "policy_failed_event_universe": policy_result.stats.get("failed_event_universe", 0),
        "policy_failed_secondary_rules": policy_result.stats.get("failed_secondary_rules", 0),
        "policy_failed_hard_gate": policy_result.stats.get("failed_hard_gate", 0),
        "policy_failed_hard_gate_breakdown": policy_result.stats.get("failed_hard_gate_breakdown", {}),
        "policy_failed_thresholds": policy_result.stats.get("failed_thresholds", 0),
        "policy_failed_trend_alignment": policy_result.stats.get("failed_trend_alignment", 0),
        "policy_failed_missing_context": policy_result.stats.get("failed_missing_context", 0),
        "articles_selected_for_extraction": len(extraction_articles),
        "articles_skipped_before_openai": skipped_before_openai,
        "execution_plans_built": len(execution_plans),
        "trade_results_published": result_stats.get("telegram", 0),
        "tracked_trades_new": tracked_new,
        "tracked_trades_active": trade_tracker.count_active(),
        "calendar_events": len(calendar_events),
        "major_event_articles": coverage_metrics["major_event_articles"],
        "major_event_impacts": coverage_metrics["major_event_impacts"],
        "major_event_decisions": coverage_metrics["major_event_decisions"],
        "source_counts": coverage_metrics.get("source_counts", {}),
        "signal_drop_total": len(signal_drop_details),
        "signal_drop_counts": _drop_counts_by_stage(signal_drop_details),
        "signal_drop_details": signal_drop_details,
    }
    return finalize(summary)
