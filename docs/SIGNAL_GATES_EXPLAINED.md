# Signal Gates Explained (Simple Version)

This document explains, in plain language, how a signal moves through the system and where it can be dropped.

## Big Picture
The system does this:
1. Collect news.
2. Convert news into FX pair impacts.
3. Score whether a trade idea is strong enough.
4. Apply strict safety rules ("gates").
5. Only publish what survives all gates.

Think of gates as security checks at an airport.  
A signal must pass every required checkpoint before it can be posted.

## Main Software and Data Sources
- `OpenAI`: extracts currency pairs and sentiment from news text.
- `NewsAPI` + `Google News RSS`: raw news feeds.
- `Alpha Vantage`: market context and intraday data (trend, RSI, technical checks, plan building).
- `FMP` (optional): economic calendar surprise context.
- `Telegram`: publishing channel.
- `Render`: hosting/runtime platform.

## End-to-End Pipeline Stages
Code path: `app/unified_pipeline.py`

1. `ingestion`
- Fetch raw articles from sources.
- If zero articles, run ends with reason `no_news`.

2. `normalization`
- Standardizes article format (timestamps, reliability, IDs, etc.).
- If zero normalized rows, reason `no_normalized_articles`.

3. Extraction prefilter (before OpenAI)
- Keeps only likely tradable/major-event articles.
- Controls:
  - `REQUIRE_MAJOR_EVENT_FILTER`
  - `MAX_EXTRACTION_ARTICLES`
- If nothing survives, reason `no_extraction_candidates`.

4. `pair_impact`
- Builds pair-level impact objects.
- Uses deterministic extractor + OpenAI pair/sentiment merge.
- If empty, reason `no_impacts`.

5. `market_context`
- Pulls technical context for pairs (trend, volatility, alignment).
- If empty, reason `no_context`.

6. `calendar` (optional)
- Adds economic surprise info.
- Disabled when `ENABLE_ECONOMIC_CALENDAR=false`.

7. `decision` (engine decision)
- Engine decides: `publish`, `hold`, or `reject`.
- This is first signal-level filter.

8. `strategy` config load
- Loads `config/major_event_strategy.json`.
- If invalid, run fails with `invalid_strategy_config`.

9. `policy` gate
- Strict rule checks based on strategy config.

10. `execution_plan`
- Requires a concrete execution plan from intraday data.

11. Publish cap
- Keeps only top N signals:
  - `MAX_PUBLISHABLE_SIGNALS_PER_RUN`

12. `publishing` guardrail
- Final kill-switch checks before posting.

## Signal-Level Gates (Where Signals Usually Drop)
These are the stages that now produce drop details in run summary.

### Gate 1: `signal_decision`
Comes from scoring engine (`app/signal_engine.py`).

Possible results:
- `publish`: can continue.
- `hold`: dropped for now.
- `reject`: dropped.

Drop reason example:
- `engine_hold`
- `engine_reject`

### Gate 2: `policy`
Comes from `app/major_event_policy.py`.

Policy checks in simple terms:
1. Event type allowed?
- Major events allowed (rate decision, inflation, employment, geopolitical).

2. Secondary-event rules
- For `risk_sentiment`, stricter minimums apply.

3. Hard gate (strict minimum quality)
- Event impact minimum.
- Pair relevance minimum.
- Source reliability minimum.
- Freshness limit (must not be stale).
- Impact-now score minimum.
- Latency class must be allowed.

4. Thresholds by volatility bucket
- Confidence must be high enough.
- Technical alignment must be high enough.

5. Trend alignment
- Bullish signal needs trend score high enough.
- Bearish signal needs trend score low enough.

Policy drop reasons:
- `event_universe`
- `secondary_rules`
- `hard_gate_<reason>`
- `thresholds`
- `trend_alignment`
- `missing_context`

Hard-gate subreasons:
- `event_impact`
- `pair_relevance`
- `source_reliability`
- `freshness_missing`
- `freshness_stale`
- `impact_now_missing`
- `impact_now`
- `latency_missing`
- `latency_class`

### Gate 3: `execution_plan`
The signal must have an execution plan.

If no plan is built, signal is dropped:
- `missing_execution_plan`

### Gate 4: `publish_cap`
If too many valid signals survive, only top N are kept.

Dropped reason:
- `max_publishable_signals_per_run`

### Gate 5: `publishing_guardrail`
Even valid signals can be blocked at final publish stage.

Common reasons:
- `publish_disabled_runtime` (manual runtime switch off)
- `publish_disabled_env` (env flag off)
- `rollback_switch_active` (rollback file present)

## Current Important Numbers (From Strategy + Config)
Main strategy file: `config/major_event_strategy.json`

Hard gate:
- `event_impact_min = 0.75`
- `pair_relevance_min = 0.70`
- `impact_now_min = 0.55`
- `source_reliability_min = 0.65`
- `freshness_max_minutes = 720` (12 hours)
- `allowed_latency_classes = ["immediate", "short_lag"]`

Secondary rules:
- `event_impact_min = 0.75`
- `pair_relevance_min = 0.70`
- `impact_now_min = 0.65`

Volatility buckets:
- `low` if ATR percentile < `0.33`
- `normal` if <= `0.66`
- else `high`

Thresholds:
- Low vol: confidence `>= 0.70`, technical alignment `>= 0.58`
- Normal vol: confidence `>= 0.73`, technical alignment `>= 0.62`
- High vol: confidence `>= 0.76`, technical alignment `>= 0.66`

Trend alignment:
- Bullish requires trend score `>= 0.52`
- Bearish requires trend score `<= 0.48`

## What "Impact Now", "Latency", "ATR Percentile" Mean
- `impact_now_score`: how likely this news moves price soon (0 to 1).
- `latency class`: timing bucket:
  - `immediate` = likely now
  - `short_lag` = likely soon (not instant)
  - `slow_burn` = slower reaction
- `ATR percentile`: relative volatility measure (how active the market is recently compared to its own history).

## New Drop-Detail Output
Run summary now includes:
- `signal_drop_total`
- `signal_drop_counts` (grouped by stage)
- `signal_drop_details` (list of dropped signals with stage + reason)

Each detail item contains:
- `stage`
- `reason`
- `signal_id`
- `pair`
- `direction` (when available)

## Where To View It
- `GET /runs?limit=...` -> per-run details, including `signal_drop_details`.
- `GET /metrics?limit=...` -> aggregate metrics.
- `/dashboard` -> top-level health and failure summaries.

## Quick Glossary
- Gate: a rule checkpoint.
- Threshold: minimum score required.
- Calibration: adjusting model confidence so percentages are more realistic.
- Guardrail: safety block to prevent unwanted publishing.
- Rollback switch: emergency stop file.
- Stale: too old to trust for current action.
