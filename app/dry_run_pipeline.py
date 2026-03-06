from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from app.entity_pair_extractor import DeterministicPairImpactExtractor
from app.market_context import (
    classify_volatility_regime,
    compute_technical_alignment_score,
)
from app.news_fetcher import fetch_forex_news
from app.publisher import (
    compose_telegram_market_update,
    format_telegram_batch,
    format_x_signal,
)
from app.schemas import MarketContext, NormalizedArticle, PairImpact, SignalCandidate
from app.signal_engine import WeightedSignalEngine
from app.utils import log

SOURCE_RELIABILITY = {
    "NewsAPI": 0.78,
    "GoogleNews": 0.65,
}

FALLBACK_ARTICLES = [
    {
        "source": "FallbackWire",
        "title": "ECB signals prolonged restrictive stance while Fed remains cautious",
        "description": "Euro gains after hawkish ECB remarks as dollar momentum cools.",
        "url": "https://example.com/fallback-eurusd",
        "published_at": "2026-02-28T00:00:00Z",
    },
    {
        "source": "FallbackWire",
        "title": "Bank of Japan maintains dovish tone and yen weakens",
        "description": "Yen falls as BOJ reiterates accommodative policy outlook.",
        "url": "https://example.com/fallback-usdjpy",
        "published_at": "2026-02-28T00:10:00Z",
    },
]


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_timestamp(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            datetime.fromisoformat(text)
            return value.strip().replace("+00:00", "Z")
        except ValueError:
            pass
    return _now_utc()


def _article_id(source: str, title: str, url: str) -> str:
    seed = f"{source}|{title}|{url}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()


def normalize_articles(raw_articles: list[dict[str, Any]]) -> list[NormalizedArticle]:
    normalized: list[NormalizedArticle] = []
    for idx, article in enumerate(raw_articles):
        source = str(article.get("source") or "Unknown").strip()
        title = str(article.get("title") or "").strip()
        summary = str(
            article.get("description")
            or article.get("summary")
            or article.get("content")
            or title
        ).strip()
        if not title:
            continue
        if not summary:
            summary = title
        url = str(article.get("url") or f"local://article/{idx}").strip()
        published_at = _normalize_timestamp(article.get("published_at"))
        fetched_at = _now_utc()

        normalized.append(
            NormalizedArticle(
                article_id=_article_id(source, title, url),
                source=source,
                url=url,
                title=title,
                summary=summary,
                published_at=published_at,
                fetched_at=fetched_at,
                language="en",
                source_reliability=SOURCE_RELIABILITY.get(source, 0.60),
            )
        )
    return normalized


def _best_pair_impacts_by_pair(impacts: list[PairImpact]) -> list[PairImpact]:
    best: dict[str, PairImpact] = {}
    for impact in impacts:
        existing = best.get(impact.pair)
        if existing is None or impact.pair_relevance_score > existing.pair_relevance_score:
            best[impact.pair] = impact
    return list(best.values())


class SyntheticMarketContextProvider:
    def build_context(self, pairs: list[str]) -> list[MarketContext]:
        contexts: list[MarketContext] = []
        timestamp = _now_utc()
        for pair in sorted(set(pairs)):
            seed = sum(ord(ch) for ch in pair)
            rsi = 30.0 + float(seed % 40)
            trend_score = ((seed * 7) % 100) / 100.0
            atr_percentile = ((seed * 11) % 100) / 100.0
            regime = classify_volatility_regime(atr_percentile)
            alignment = compute_technical_alignment_score(
                rsi=rsi,
                trend_score=trend_score,
                atr_percentile=atr_percentile,
            )
            contexts.append(
                MarketContext(
                    pair=pair,
                    timestamp=timestamp,
                    rsi=rsi,
                    trend_score=trend_score,
                    volatility_regime=regime,
                    atr_percentile=atr_percentile,
                    technical_alignment_score=alignment,
                )
            )
        return contexts


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_dry_pipeline(
    raw_articles: list[dict[str, Any]] | None = None,
    output_dir: str = "artifacts/dry_run",
) -> dict[str, Any]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if raw_articles is None:
        fetched = fetch_forex_news()
        raw_articles = fetched if fetched else FALLBACK_ARTICLES

    normalized_articles = normalize_articles(raw_articles)
    extractor = DeterministicPairImpactExtractor()

    pair_impacts_all: list[PairImpact] = []
    for article in normalized_articles:
        pair_impacts_all.extend(extractor.extract_pair_impacts(article))
    pair_impacts = _best_pair_impacts_by_pair(pair_impacts_all)

    context_provider = SyntheticMarketContextProvider()
    contexts = context_provider.build_context([impact.pair for impact in pair_impacts])

    engine = WeightedSignalEngine()
    decisions = engine.evaluate_signals(pair_impacts, contexts)

    publishable_signals: list[SignalCandidate] = [
        decision.signal
        for decision in decisions
        if decision.decision == "publish" and decision.signal is not None
    ]

    simulated_posts = {
        "telegram_market_update_preview": compose_telegram_market_update(
            articles=normalized_articles,
            impacts=pair_impacts,
            contexts=contexts,
            decisions=decisions,
            signals=publishable_signals,
            include_disclaimer=True,
        ),
        "telegram_preview": format_telegram_batch(publishable_signals, include_disclaimer=True),
        "x_previews": [format_x_signal(signal, include_disclaimer=True) for signal in publishable_signals],
    }

    decision_payload = []
    for decision in decisions:
        decision_payload.append(
            {
                "decision": decision.decision,
                "confidence_raw": round(decision.confidence_raw, 6),
                "confidence_calibrated": round(decision.confidence_calibrated, 6),
                "signal": asdict(decision.signal) if decision.signal else None,
                "reasons": decision.reasons,
                "impact_timing": asdict(decision.impact_timing)
                if decision.impact_timing
                else None,
            }
        )

    _write_json(output_path / "normalized_articles.json", [asdict(item) for item in normalized_articles])
    _write_json(output_path / "pair_impacts.json", [asdict(item) for item in pair_impacts])
    _write_json(output_path / "market_context.json", [asdict(item) for item in contexts])
    _write_json(output_path / "decisions.json", decision_payload)
    _write_json(output_path / "simulated_posts.json", simulated_posts)

    summary = {
        "run_mode": "dry_run",
        "generated_at": _now_utc(),
        "input_articles": len(raw_articles),
        "normalized_articles": len(normalized_articles),
        "pair_impacts": len(pair_impacts),
        "market_contexts": len(contexts),
        "decisions": len(decisions),
        "publishable_signals": len(publishable_signals),
        "output_dir": str(output_path.resolve()),
    }
    _write_json(output_path / "summary.json", summary)

    log(f"Dry run completed. Artifacts written to: {summary['output_dir']}")
    return summary
