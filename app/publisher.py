from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import html
import re
from typing import Any

from app.config import ENABLE_CHART_IMAGES, ENABLE_TELEGRAM_IMAGES, TELEGRAM_IMAGE_MODE
from app.signal_setup import SignalExecutionPlan
from app.schemas import MarketContext, NormalizedArticle, PairImpact, SignalCandidate
from app.telegram_bot import send_telegram_message, send_telegram_photo
from app.trade_tracker import TradeUpdate, format_trade_result_update
from app.visual_selector import VisualAttachment, build_visual_attachment
from app.twitter_sender import send_tweet
from app.utils import log

DEFAULT_DISCLAIMER = (
    "Disclaimer: Educational content only, not financial advice."
)
TELEGRAM_MAX_MESSAGE_CHARS = 3900


@dataclass(slots=True)
class PublisherConfig:
    enable_telegram: bool = True
    enable_x: bool = False
    include_disclaimer: bool = True
    telegram_parse_mode: str = "Markdown"
    max_news_briefs: int = 3
    max_verdicts: int = 3
    enable_images: bool = ENABLE_TELEGRAM_IMAGES
    image_mode: str = TELEGRAM_IMAGE_MODE
    enable_chart_images: bool = ENABLE_CHART_IMAGES


def _normalize_thesis(thesis: str, max_len: int = 110) -> str:
    text = " ".join(thesis.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _clean_text(text: str) -> str:
    if not text:
        return ""
    cleaned = html.unescape(str(text))
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _shorten(text: str, max_len: int) -> str:
    compact = _clean_text(text)
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3].rstrip() + "..."


def _md_escape(text: str) -> str:
    if not text:
        return ""
    escaped = str(text)
    for token in ("\\", "*", "_", "`", "[", "]", "(", ")"):
        escaped = escaped.replace(token, f"\\{token}")
    return escaped


def _split_for_telegram(text: str, max_chars: int = TELEGRAM_MAX_MESSAGE_CHARS) -> list[str]:
    compact = str(text or "").strip()
    if not compact:
        return []
    if len(compact) <= max_chars:
        return [compact]

    parts: list[str] = []
    current = ""

    # Prefer splitting on section breaks first, then line breaks, then hard split.
    for paragraph in compact.split("\n\n"):
        candidate = paragraph.strip()
        if not candidate:
            continue

        if not current:
            if len(candidate) <= max_chars:
                current = candidate
                continue
            lines = candidate.split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if len(line) <= max_chars:
                    if current and len(current) + 1 + len(line) > max_chars:
                        parts.append(current)
                        current = line
                    else:
                        current = f"{current}\n{line}" if current else line
                    continue
                # Hard split very long line.
                remaining = line
                while len(remaining) > max_chars:
                    chunk = remaining[:max_chars]
                    if current:
                        parts.append(current)
                        current = ""
                    parts.append(chunk)
                    remaining = remaining[max_chars:]
                if remaining:
                    current = remaining if not current else f"{current}\n{remaining}"
            continue

        if len(current) + 2 + len(candidate) <= max_chars:
            current = f"{current}\n\n{candidate}"
            continue

        parts.append(current)
        if len(candidate) <= max_chars:
            current = candidate
            continue

        remaining = candidate
        while len(remaining) > max_chars:
            parts.append(remaining[:max_chars])
            remaining = remaining[max_chars:]
        current = remaining

    if current:
        parts.append(current)

    return parts


def _impact_level(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.50:
        return "medium"
    return "low"


def _impact_window(event_type: str) -> str:
    if event_type in {"rate_decision", "inflation", "employment", "geopolitical"}:
        return "immediate"
    if event_type == "risk_sentiment":
        return "same_session"
    return "next_session"


def _state_label(decision: str) -> str:
    mapping = {
        "publish": "signal_ready",
        "hold": "watchlist",
        "reject": "no_trade",
    }
    return mapping.get(decision, "watchlist")


def _why_it_matters_fx(event_type: str, pair: str) -> str:
    if event_type == "rate_decision":
        return f"Rate expectations can reprice {pair} quickly."
    if event_type == "inflation":
        return f"Inflation data can shift policy expectations for {pair}."
    if event_type == "employment":
        return f"Labor data can move growth and rate outlook in {pair}."
    if event_type == "geopolitical":
        return f"Risk sentiment can trigger fast rotations in {pair}."
    if event_type == "risk_sentiment":
        return f"Risk-on/risk-off flow may drive short-term moves in {pair}."
    return f"This update may influence near-term flow in {pair}."


def _reason_snippet(reasons: list[str], max_items: int = 3) -> str:
    if not reasons:
        return "event and technical context aligned"
    picked: list[str] = []
    for reason in reasons:
        if reason.startswith(("event=", "technical_alignment=", "impact_now=", "impact_latency=")):
            picked.append(reason)
        if len(picked) >= max_items:
            break
    if not picked:
        picked = reasons[:max_items]
    return "; ".join(picked)


def _parse_event_label(reason_items: list[str], fallback_event_type: str | None = None) -> str:
    for reason in reason_items:
        if reason.startswith("event="):
            value = reason.split("=", 1)[1].strip()
            if value:
                return value.replace("_", " ")
    if fallback_event_type:
        return fallback_event_type.replace("_", " ")
    return "macro"


def _compact_signal_message(
    article: NormalizedArticle,
    pair_impact: PairImpact,
    signal: SignalCandidate,
    include_disclaimer: bool,
    execution_plan: SignalExecutionPlan | None = None,
) -> str:
    headline = _md_escape(_shorten(article.title, max_len=90))
    summary = _md_escape(_shorten(article.summary, max_len=150))
    why = _md_escape(_why_it_matters_fx(pair_impact.event_type, signal.pair))
    event_label = _parse_event_label(signal.reasons, pair_impact.event_type)
    verdict_why = _md_escape(
        f"{event_label.capitalize()} context aligns with current {signal.direction} momentum on {signal.pair}."
    )
    if execution_plan is not None:
        when_to_enter = _md_escape(execution_plan.when_to_enter)
        risk_line = _md_escape(execution_plan.risk_line_text)
        valid_for = f"Next {execution_plan.valid_for_hours} hours."
    else:
        if signal.direction == "bullish":
            when_to_enter = "Enter only after a 1h candle closes bullish above recent resistance."
            risk_line = "Exit if a 1h candle closes back below setup level."
        else:
            when_to_enter = "Enter only after a 1h candle closes bearish below recent support."
            risk_line = "Exit if a 1h candle closes back above setup level."
        valid_for = "Next 6 hours."

    risk_line = _md_escape(risk_line)
    verdict = f"{signal.pair} — {signal.direction.upper()}"

    parts = [
        "*Signalyze AI Update*",
        f"*News:* {headline}",
        f"*Summary:* {summary}",
        f"*Why It Matters:* {why}",
        f"*Verdict:* *{_md_escape(verdict)}*",
        f"*Why This Verdict:* {verdict_why}",
        f"*When To Enter:* {_md_escape(when_to_enter)}",
        f"*Risk Line:* {risk_line}",
        f"*Valid For:* {_md_escape(valid_for)}",
    ]

    if include_disclaimer:
        parts.append(f"_{_md_escape(DEFAULT_DISCLAIMER)}_")

    return "\n\n".join(parts)


def format_telegram_signal(signal: SignalCandidate) -> str:
    return (
        f"*{signal.pair}* | {signal.direction.upper()} | {signal.horizon}\n"
        f"Signal ID: `{signal.signal_id}`\n"
        f"Confidence: `{signal.confidence_calibrated:.2f}`\n"
        f"Thesis: {signal.thesis}\n"
        f"Invalidation: {signal.invalidation}\n"
        f"Time (UTC): {signal.created_at}"
    )


def format_telegram_batch(
    signals: list[SignalCandidate],
    include_disclaimer: bool = True,
) -> str:
    if not signals:
        return "No publishable signals."

    header = "Signalyze AI Free Signals\n"
    body = "\n\n".join(format_telegram_signal(signal) for signal in signals)
    sections = [header + "\n" + body]
    if include_disclaimer:
        sections.append(DEFAULT_DISCLAIMER)
    return "\n\n".join(sections)


def format_telegram_news_brief(brief: dict[str, Any]) -> str:
    pairs = ", ".join(brief["affected_pairs"]) if brief["affected_pairs"] else "n/a"
    return (
        "News Brief\n"
        f"{brief['headline']}\n\n"
        f"Summary: {brief['summary_1l']}\n"
        f"Why it matters (FX): {brief['why_it_matters_fx']}\n"
        f"Pairs: {pairs}\n"
        f"Impact: {brief['impact_level']} | {brief['impact_window']}\n"
        f"Source: {brief['source_name']} - {brief['source_url']}\n"
        f"Time (UTC): {brief['timestamp_utc']}\n"
        f"Ref: {brief['post_id']}"
    )


def format_telegram_verdict(verdict: dict[str, Any]) -> str:
    return (
        f"Verdict - {verdict['pair']}\n"
        f"Bias: {verdict['bias']}\n"
        f"Confidence: {verdict['confidence']:.2f}\n"
        f"State: {verdict['state']}\n"
        f"Thesis: {verdict['thesis']}\n"
        f"Trigger: {verdict['trigger_condition']}\n"
        f"Invalidation: {verdict['invalidation_condition']}\n"
        f"Horizon: {verdict['time_horizon']}\n"
        f"Ref: {verdict['related_post_id']}\n"
        f"Time (UTC): {verdict['timestamp_utc']}"
    )


def format_telegram_signal_alert(signal: SignalCandidate) -> str:
    return (
        f"Signal Ready - {signal.pair} {signal.direction}\n"
        f"Confidence: {signal.confidence_calibrated:.2f}\n"
        f"Why now: {_reason_snippet(signal.reasons)}\n"
        "Setup: Follow direction when 1h momentum confirms.\n"
        f"Invalidation: {signal.invalidation}\n"
        f"Horizon: {signal.horizon}\n"
        f"Signal ID: {signal.signal_id}\n"
        f"Time (UTC): {signal.created_at}"
    )


def _build_news_briefs(
    articles: list[NormalizedArticle],
    impacts: list[PairImpact],
    max_items: int,
) -> list[dict[str, Any]]:
    article_by_id = {article.article_id: article for article in articles}
    impacts_by_article: dict[str, list[PairImpact]] = defaultdict(list)
    article_scores: dict[str, float] = {}

    for impact in impacts:
        impacts_by_article[impact.article_id].append(impact)
        score = impact.pair_relevance_score * impact.event_impact_score
        existing = article_scores.get(impact.article_id, 0.0)
        if score > existing:
            article_scores[impact.article_id] = score

    top_ids = sorted(article_scores.keys(), key=lambda aid: article_scores[aid], reverse=True)[:max_items]

    briefs: list[dict[str, Any]] = []
    for article_id in top_ids:
        article = article_by_id.get(article_id)
        if article is None:
            continue
        article_impacts = impacts_by_article.get(article_id, [])
        if not article_impacts:
            continue

        best_impact = max(article_impacts, key=lambda impact: impact.event_impact_score)
        affected_pairs = sorted({impact.pair for impact in article_impacts})

        briefs.append(
            {
                "post_id": article.article_id[:8],
                "timestamp_utc": article.published_at,
                "headline": _shorten(article.title, max_len=130),
                "summary_1l": _shorten(article.summary, max_len=170),
                "why_it_matters_fx": _why_it_matters_fx(best_impact.event_type, best_impact.pair),
                "affected_pairs": affected_pairs,
                "impact_window": _impact_window(best_impact.event_type),
                "impact_level": _impact_level(best_impact.event_impact_score),
                "source_name": article.source,
                "source_url": article.url,
            }
        )

    return briefs


def _build_verdicts(
    decisions: list[Any],
    impacts: list[PairImpact],
    contexts: list[MarketContext],
    max_items: int,
) -> list[dict[str, Any]]:
    impact_by_pair = {impact.pair: impact for impact in impacts}
    context_by_pair = {context.pair: context for context in contexts}

    eligible = [decision for decision in decisions if getattr(decision, "signal", None) is not None]
    if not eligible:
        return []

    priority = {"publish": 0, "hold": 1, "reject": 2}
    ordered = sorted(
        eligible,
        key=lambda decision: (
            priority.get(getattr(decision, "decision", "hold"), 3),
            -float(getattr(decision, "confidence_calibrated", 0.0)),
        ),
    )

    verdicts: list[dict[str, Any]] = []
    for decision in ordered[:max_items]:
        signal = decision.signal
        impact = impact_by_pair.get(signal.pair)
        context = context_by_pair.get(signal.pair)

        if getattr(decision, "decision", "") == "publish":
            trigger = "Setup is active with aligned event and momentum context."
        elif getattr(decision, "decision", "") == "hold":
            trigger = "Wait for cleaner 1h candle confirmation before activation."
        else:
            trigger = "No reliable alignment yet; keep this on low priority watch."

        event_label = "macro event"
        if impact is not None:
            event_label = impact.event_type.replace("_", " ")

        trend_hint = ""
        if context is not None:
            trend_hint = f" Trend score is {context.trend_score:.2f}."

        verdicts.append(
            {
                "related_post_id": (impact.article_id[:8] if impact else "n/a"),
                "pair": signal.pair,
                "bias": signal.direction,
                "confidence": float(getattr(decision, "confidence_calibrated", signal.confidence_calibrated)),
                "state": _state_label(getattr(decision, "decision", "hold")),
                "thesis": _shorten(
                    f"{event_label} context supports a {signal.direction} bias on {signal.pair}.{trend_hint}",
                    max_len=180,
                ),
                "trigger_condition": trigger,
                "invalidation_condition": signal.invalidation,
                "time_horizon": signal.horizon,
                "timestamp_utc": signal.created_at,
            }
        )

    return verdicts


def format_telegram_market_update(
    briefs: list[dict[str, Any]],
    verdicts: list[dict[str, Any]],
    signals: list[SignalCandidate],
    include_disclaimer: bool = True,
) -> str:
    sections = ["Signalyze AI Market Update"]

    if briefs:
        brief_block = "\n\n".join(format_telegram_news_brief(brief) for brief in briefs)
        sections.append(f"News\n\n{brief_block}")

    if verdicts:
        verdict_block = "\n\n".join(format_telegram_verdict(verdict) for verdict in verdicts)
        sections.append(f"Verdicts\n\n{verdict_block}")

    if signals:
        signal_block = "\n\n".join(format_telegram_signal_alert(signal) for signal in signals)
        sections.append(f"Signal Alerts\n\n{signal_block}")

    if include_disclaimer:
        sections.append(DEFAULT_DISCLAIMER)

    return "\n\n".join(sections)


def compose_telegram_market_update(
    articles: list[NormalizedArticle],
    impacts: list[PairImpact],
    contexts: list[MarketContext],
    decisions: list[Any],
    signals: list[SignalCandidate],
    include_disclaimer: bool = True,
    max_news_briefs: int = 3,
    max_verdicts: int = 3,
    execution_plans: dict[str, SignalExecutionPlan] | None = None,
) -> str:
    _ = contexts
    _ = decisions
    _ = max_news_briefs
    _ = max_verdicts

    article_by_id = {article.article_id: article for article in articles}
    impact_by_pair = {impact.pair: impact for impact in impacts}

    messages: list[str] = []
    for signal in signals:
        impact = impact_by_pair.get(signal.pair)
        if impact is None:
            continue
        article = article_by_id.get(impact.article_id)
        if article is None:
            continue
        messages.append(
            _compact_signal_message(
                article=article,
                pair_impact=impact,
                signal=signal,
                include_disclaimer=include_disclaimer,
                execution_plan=(execution_plans or {}).get(signal.signal_id),
            )
        )

    return "\n\n---\n\n".join(messages)


def format_x_signal(signal: SignalCandidate, include_disclaimer: bool = True) -> str:
    # Keep posts compact so they fit 280 chars for free-tier posting.
    base = (
        f"{signal.pair} {signal.direction.upper()} | conf {signal.confidence_calibrated:.2f}\n"
        f"{_normalize_thesis(signal.thesis)}\n"
        f"Inv: {_normalize_thesis(signal.invalidation, max_len=70)}\n"
        f"id:{signal.signal_id}"
    )
    if include_disclaimer:
        candidate = f"{base}\nNFA"
        if len(candidate) <= 280:
            return candidate
    if len(base) <= 280:
        return base
    return base[:277] + "..."


class SignalPublisher:
    def __init__(self, config: PublisherConfig | None = None):
        self.config = config or PublisherConfig()

    def publish_signals(self, signals: list[SignalCandidate]) -> dict[str, int]:
        if not signals:
            log("No signals to publish.")
            return {"telegram": 0, "x": 0}

        telegram_count = 0
        x_count = 0

        if self.config.enable_telegram:
            message = format_telegram_batch(
                signals=signals,
                include_disclaimer=self.config.include_disclaimer,
            )
            if send_telegram_message(message, parse_mode=self.config.telegram_parse_mode):
                telegram_count = len(signals)

        if self.config.enable_x:
            for signal in signals:
                tweet = format_x_signal(
                    signal,
                    include_disclaimer=self.config.include_disclaimer,
                )
                if send_tweet(tweet):
                    x_count += 1

        return {"telegram": telegram_count, "x": x_count}

    def publish_market_narrative(
        self,
        articles: list[NormalizedArticle],
        impacts: list[PairImpact],
        contexts: list[MarketContext],
        decisions: list[Any],
        signals: list[SignalCandidate],
        execution_plans: dict[str, SignalExecutionPlan] | None = None,
    ) -> dict[str, int]:
        if not self.config.enable_telegram:
            return {
                "telegram": 0,
                "x": 0,
                "news_briefs": 0,
                "verdicts": 0,
                "signal_alerts": 0,
                "images": 0,
            }
        _ = contexts
        _ = decisions

        article_by_id = {article.article_id: article for article in articles}
        impact_by_pair = {impact.pair: impact for impact in impacts}

        posts: list[tuple[str, VisualAttachment | None]] = []
        for signal in signals:
            impact = impact_by_pair.get(signal.pair)
            if impact is None:
                continue
            article = article_by_id.get(impact.article_id)
            if article is None:
                continue
            execution_plan = (execution_plans or {}).get(signal.signal_id)
            caption = _compact_signal_message(
                article=article,
                pair_impact=impact,
                signal=signal,
                include_disclaimer=self.config.include_disclaimer,
                execution_plan=execution_plan,
            )
            visual = None
            if self.config.enable_images:
                visual = build_visual_attachment(
                    article=article,
                    pair_impact=impact,
                    signal=signal,
                    execution_plan=execution_plan,
                    image_mode=self.config.image_mode,
                    enable_chart_images=self.config.enable_chart_images,
                )
            posts.append((caption, visual))

        if not posts:
            log("No signal-linked news posts to publish.")
            return {
                "telegram": 0,
                "x": 0,
                "news_briefs": 0,
                "verdicts": 0,
                "signal_alerts": 0,
                "images": 0,
            }

        log(f"Publishing {len(posts)} compact signal post(s) to Telegram.")
        sent_count = 0
        image_count = 0
        for post, visual in posts:
            message_parts = _split_for_telegram(post, TELEGRAM_MAX_MESSAGE_CHARS)
            sent_all_parts = True

            if visual is not None and message_parts:
                first_part = message_parts[0]
                send_full_first_part = len(first_part) > 1000
                photo_caption = (
                    "Signalyze AI Visual Context\n"
                    f"Image type: {visual.kind}\n"
                    f"Source: {visual.source}"
                    if send_full_first_part
                    else first_part
                )
                sent_photo = send_telegram_photo(
                    photo_url=visual.image_url,
                    caption=photo_caption,
                    parse_mode=self.config.telegram_parse_mode,
                )
                if sent_photo:
                    image_count += 1
                    if not send_full_first_part:
                        message_parts = message_parts[1:]
                else:
                    log(
                        f"Telegram photo failed for visual kind={visual.kind}, "
                        f"source={visual.source}; falling back to text."
                    )

            for part in message_parts:
                ok = send_telegram_message(part, parse_mode=self.config.telegram_parse_mode)
                if not ok:
                    sent_all_parts = False
                    break
            if sent_all_parts:
                sent_count += 1

        return {
            "telegram": sent_count,
            "x": 0,
            "news_briefs": sent_count,
            "verdicts": sent_count,
            "signal_alerts": sent_count,
            "images": image_count,
        }

    def publish_trade_result_updates(self, updates: list[TradeUpdate]) -> dict[str, int]:
        if not self.config.enable_telegram:
            return {"telegram": 0, "x": 0}
        if not updates:
            return {"telegram": 0, "x": 0}

        sent = 0
        for update in updates:
            text = format_trade_result_update(update)
            if send_telegram_message(text, parse_mode=self.config.telegram_parse_mode):
                sent += 1

        return {"telegram": sent, "x": 0}
