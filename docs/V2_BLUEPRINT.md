# Signalyze AI V2 Blueprint

## Goal

Build a reliable, explainable forex signal engine that can grow from free Telegram/X distribution into a paid product.

## Product Outcome

- Free tier publishes consistent, transparent signals with timestamps, confidence, and invalidation rules.
- Internal system tracks forward performance and calibrates confidence over time.
- Architecture supports later monetization (premium channels, dashboard, API).

## Working Assumptions (Version 1)

- Initial audience: beginner/intermediate discretionary forex traders.
- Pair universe: major pairs first (`EUR/USD`, `USD/JPY`, `GBP/USD`, `USD/CHF`, `AUD/USD`, `USD/CAD`, `NZD/USD`).
- Signal horizon for launch: `intraday` (4h to 24h).
- Publication model: quality over quantity (2-8 signals/day target).

## V2 Architecture (Module by Module)

1. `ingestion`

- Pull articles from multiple sources.
- Attach fetch timestamp, source id, URL hash.
- Deduplicate by normalized title + URL + short text fingerprint.

2. `normalization`

- Convert raw articles to a canonical `NormalizedArticle` schema.
- Clean HTML/noise and truncate fields to safe bounds.
- Run language guard (`en` only for V1).

3. `entity_pair_extractor`

- Deterministic pass first:
  - Detect currencies, central banks, country mentions, macro terms.
  - Map entities to candidate pairs.
- LLM pass second:
  - Used only when deterministic confidence is low.
  - Returns strict JSON for pair attribution.

4. `event_classifier`

- Classify event type (`rate_decision`, `inflation`, `employment`, `geopolitical`, `risk_sentiment`, `other`).
- Score event impact magnitude (`0-1`) and direction by pair.

5. `market_context`

- Pull technical and market-state features per candidate pair:
  - RSI, trend slope, ATR percentile, volatility regime, session.
- Produce `MarketContext` and `technical_alignment_score`.

6. `signal_engine`

- Combine news impact + pair attribution + sentiment + technical context.
- Compute confidence using weighted score + calibration layer.
- Output `SignalCandidate` with:
  - direction (`bullish` or `bearish`)
  - confidence
  - thesis summary
  - invalidation condition
  - expected horizon

7. `quality_gate`

- Block low-quality or ambiguous outputs:
  - Minimum confidence threshold.
  - Minimum source reliability.
  - Duplicate/similar signal suppression window.
  - Cooldown per pair.

8. `publisher`

- Format posts for Telegram and X with free-tier template.
- Attach disclaimer and signal id.
- Store published payload for audit/replay.

9. `evaluation`

- Record post-publication outcomes at fixed checkpoints.
- Track directional accuracy, adverse excursion proxy, confidence calibration error.
- Feed metrics into threshold tuning.

## Canonical Data Schemas

Use these as internal contracts.

### NormalizedArticle

```json
{
  "article_id": "sha256(...)",
  "source": "NewsAPI",
  "url": "https://...",
  "title": "ECB signals prolonged restrictive stance",
  "summary": "Short cleaned summary",
  "published_at": "2026-02-28T00:00:00Z",
  "fetched_at": "2026-02-28T00:01:02Z",
  "language": "en",
  "source_reliability": 0.78
}
```

### PairImpact

```json
{
  "article_id": "sha256(...)",
  "pair": "EUR/USD",
  "direction_hint": "bearish",
  "pair_relevance_score": 0.82,
  "event_type": "rate_decision",
  "event_impact_score": 0.74,
  "explanation": "Hawkish ECB supports EUR relative to USD expectations"
}
```

### MarketContext

```json
{
  "pair": "EUR/USD",
  "timestamp": "2026-02-28T00:05:00Z",
  "rsi": 63.4,
  "trend_score": 0.58,
  "volatility_regime": "normal",
  "atr_percentile": 0.61,
  "technical_alignment_score": 0.66
}
```

### SignalCandidate

```json
{
  "signal_id": "sig_20260228_0001",
  "pair": "EUR/USD",
  "direction": "bearish",
  "horizon": "intraday",
  "confidence_raw": 0.71,
  "confidence_calibrated": 0.68,
  "thesis": "Policy divergence pressure with confirming momentum",
  "invalidation": "Close above 1.0945 on 1h candle",
  "reasons": [
    "High pair relevance from macro event",
    "Technical alignment positive"
  ],
  "created_at": "2026-02-28T00:06:00Z"
}
```

### OutcomeRecord

```json
{
  "signal_id": "sig_20260228_0001",
  "evaluated_at": "2026-02-28T12:00:00Z",
  "horizon": "intraday",
  "directional_success": true,
  "max_favorable_excursion": 0.0041,
  "max_adverse_excursion": 0.0023
}
```

## Scoring Formula (V2 Baseline)

Weighted score:

`z = 1.25*pair_relevance + 1.10*event_impact + 0.90*sentiment_strength + 1.00*technical_alignment + 0.60*trend_score + 0.40*freshness + 0.35*source_reliability - 0.55*volatility_risk_penalty - 0.50*conflict_penalty`

Convert to confidence:

`confidence_raw = sigmoid(z)`

Direction:

- `bullish` if directional evidence > 0
- `bearish` if directional evidence < 0

Publish threshold (intraday start point):

- publish if `confidence_calibrated >= 0.67`
- hold if `0.58 <= confidence_calibrated < 0.67`
- reject if `< 0.58`

Calibration:

- Start with isotonic or Platt scaling using forward-test outcomes after at least 100 signals.

## Free-Tier Signal Format (Distribution Contract)

Every published signal must include:

- signal id
- pair
- direction
- confidence
- horizon
- concise thesis
- invalidation level/rule
- timestamp (UTC)
- disclaimer text

## Reliability and Guardrails

- No `eval` or unsafe parsing anywhere.
- API calls must include timeout + status check + retry policy.
- Redact secrets from logs and error output.
- Store all model inputs/outputs needed for traceability.

## KPI Dashboard (Start Tracking Immediately)

- publication_count/day
- click-through or engagement per post
- 24h retention in Telegram channel
- signal directional accuracy by horizon
- confidence calibration error (Brier score)
- false-positive rate by pair

## Two-Week Build Plan (Execution)

### Week 1: Core engine contracts and signal quality baseline

Day 1:

- Freeze schemas (`NormalizedArticle`, `PairImpact`, `MarketContext`, `SignalCandidate`).
- Acceptance: module interfaces compile and tests enforce schema presence.

Day 2:

- Implement deterministic entity/pair extraction.
- Acceptance: unit tests for mapping entities to major pairs.

Day 3:

- Add event classification + impact scoring rules.
- Acceptance: tests for key event classes and scoring ranges.

Day 4:

- Expand market context features beyond RSI.
- Acceptance: technical feature tests with mocked market data.

Day 5:

- Implement weighted scoring and publish thresholds.
- Acceptance: deterministic fixtures produce expected publish/hold/reject.

Day 6:

- Build publisher templates for Telegram/X with required fields.
- Acceptance: snapshot tests for post formatting.

Day 7:

- Integrate end-to-end dry run mode (no external posting).
- Acceptance: full pipeline run writes candidates and simulated posts.

### Week 2: Evaluation, operations, and launch readiness

Day 8:

- Add outcome tracker for forward-test records.
- Acceptance: signal-to-outcome linkage for at least one horizon.

Day 9:

- Add retries/backoff and rate-limit handling for external APIs.
- Acceptance: resilience tests for transient failures.

Day 10:

- Add structured logging + run metrics counters.
- Acceptance: logs include signal id, stage, latency, result.

Day 11:

- Add confidence calibration job scaffold (no heavy tuning yet).
- Acceptance: calibration script runs on mock outcomes.

Day 12:

- Add CI (unit tests + lint) and branch quality gate.
- Acceptance: CI blocks failing tests.

Day 13:

- Shadow run for one full day on real feeds, no public posting.
- Acceptance: report with signal count, rejection causes, stability issues.

Day 14:

- Launch free-tier posting with safety guardrails and rollback switch.
- Acceptance: first production day report and next tuning actions.

## Week 2 Status (2026-03-05)

- Day 11 complete:
  - `app/confidence_calibration.py` + `app/calibration_job.py` scaffolded.
  - Calibration model saved to `artifacts/live/calibration_model.json`.
  - Live signal engine consumes fitted model when available.
- Day 12 complete:
  - CI workflow added at `.github/workflows/ci.yml`.
  - Lint + unit tests enforce branch quality gate.
- Day 13 complete:
  - Shadow run session/report tooling added (`app/shadow_run.py`, `app/shadow_run_job.py`).
  - Report outputs include signal volume, rejection causes, and stability issues.
- Day 14 complete:
  - Guardrails added: runtime publish disable, env publish switch, file rollback switch, per-run signal cap.
  - Run history persisted for production-day reporting.
  - Production report job added (`app/launch_report.py`, `app/launch_report_job.py`).

## Definition of Done for V2

- End-to-end pipeline produces auditable, explainable signals.
- Confidence thresholds are enforced and measurable.
- Publishing format is stable and compliant with disclaimer policy.
- Forward-test metrics are collected automatically.
- Team can answer: "Why was this signal posted?" with stored evidence.

## Open Product Decisions (Resolve Before Week 1 Ends)

- Exact signal horizon set: `4h`, `8h`, or `24h`.
- Per-day max signals cap.
- Free-tier delay policy vs potential paid real-time tier.
- Minimum confidence threshold for public posting.
- Regional compliance/disclaimer text version.
