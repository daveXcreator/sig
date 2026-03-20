# Signalyze AI

AI-assisted forex signal engine that combines:
- News ingestion
- Pair detection from news context
- Pair-level sentiment scoring
- RSI confirmation
- Distribution to Telegram and X
- Narrative-first publishing (News Brief -> Verdict -> Signal Alert)

Ingestion now uses multi-query source coverage (policy, macro, labor/inflation, and geopolitical query packs) with near-duplicate suppression.

## Current Strategy
- Phase 1 (free): Publish high-quality, transparent signals on Telegram and X to build trust and audience.
- Phase 2 (monetize): Introduce premium tiers once signal quality and audience retention are proven.

## V2 Blueprint
- Detailed build spec: [docs/V2_BLUEPRINT.md](docs/V2_BLUEPRINT.md)

## Signal Gate Guide
- Plain-language gate and threshold walkthrough: [docs/SIGNAL_GATES_EXPLAINED.md](docs/SIGNAL_GATES_EXPLAINED.md)
- Free-tier runtime mode: [docs/FREE_TIER_MODE.md](docs/FREE_TIER_MODE.md)

## Execution Checklist

### Product and Market
- [ ] Define ICP v1 (who we serve first, in one sentence).
- [ ] Define positioning statement and clear promise.
- [ ] Define signal format standard (fields, confidence, risk label, timestamp).
- [ ] Define KPI targets (engagement, retention, conversion, signal hit-rate proxy).

### Signal Quality and Trust
- [ ] Build backtest + forward-test pipeline and public scorecard.
- [ ] Track false positives/negatives and iterate thresholds.
- [ ] Add explicit risk/disclaimer text to every published signal.
- [ ] Publish weekly performance recap.

### Engineering and Operations
- [x] Fix orchestration data-flow contract issues.
- [x] Remove unsafe `eval` parsing and enforce structured parsing.
- [x] Migrate OpenAI integration to modern SDK patterns.
- [x] Add baseline unit tests for core logic.
- [x] Add `.gitignore` and basic repo hygiene.
- [ ] Add retries/backoff/circuit breaking for external APIs.
- [x] Add structured logging and run metrics counters.
- [x] Add CI checks (lint + unit tests).
- [ ] Add deployment target and runtime supervisor.

### Distribution and Growth
- [ ] Define publishing cadence and channel SOP.
- [x] Build content templates for Telegram and X.
- [ ] Implement growth loop: CTA -> channel join -> feedback -> retention.
- [ ] Start weekly experiments (headline style, publish times, pair focus).

### Compliance and Risk
- [ ] Validate financial-content constraints by target region.
- [ ] Add legal disclaimers and non-advisory positioning in profiles/posts.
- [ ] Build incident protocol for bad signals or account restrictions.

### Monetization Roadmap
- [ ] Define free vs pro feature boundary.
- [ ] Define pricing hypothesis and packaging.
- [ ] Implement entitlement and billing plan.
- [ ] Pilot with first 10-20 paying users.

## Quick Start
1. Create and activate a virtual environment.
2. Install dependencies from `requirements.txt`.
3. Populate `.env` with required keys (`OPENAI_API_KEY` is required for live V2). Add `FMP_API_KEY` to enable calendar-based surprise scoring. Set `ENABLE_ECONOMIC_CALENDAR=false` to skip calendar integration.
   Free-tier mode:
   - `FREE_TIER_MODE=true`
   - `ENABLE_LOCAL_RUN_HISTORY=false`
   - `ENABLE_TRADE_TRACKING=false`
   - `ENABLE_FILE_ROLLBACK_SWITCH=false`
   - `ENABLE_BACKGROUND_LOOP=false`
   - `ROLLBACK_SWITCH_ACTIVE=false`
   Optional external run history with Supabase:
   - `RUN_HISTORY_REMOTE_BACKEND=supabase`
   - `SUPABASE_URL=...`
   - `SUPABASE_SERVICE_ROLE_KEY=...`
   - `RUN_HISTORY_SUPABASE_TABLE=signalyze_run_history`
   Day 14 launch guardrails:
   - `ENABLE_PUBLIC_POSTING=true` global publish switch.
   - `ROLLBACK_SWITCH_FILE=artifacts/live/ROLLBACK` file-based emergency rollback switch.
   - `MAX_PUBLISHABLE_SIGNALS_PER_RUN=3` safety cap per run.
   Throughput controls:
   - `MAX_EXTRACTION_ARTICLES=20` limits OpenAI extraction workload per run.
   - `REQUIRE_MAJOR_EVENT_FILTER=true` skips non-major/non-tradable news before OpenAI.
   Day 11 calibration settings:
   - `ENABLE_CONFIDENCE_CALIBRATION=true` enable fitted confidence calibration.
   - `CALIBRATION_MODEL_PATH=artifacts/live/calibration_model.json` model output path.
   - `RUN_HISTORY_PATH=artifacts/live/run_history.jsonl` run history for production reports.
   News query packs are tunable in `config/news_query_packs.json`.
   Optional override path: `NEWS_QUERY_CONFIG_PATH=...`.
   Optional image posting controls:
   - `ENABLE_TELEGRAM_IMAGES=true` to attach visuals to signal-linked posts.
   - `TELEGRAM_IMAGE_MODE=auto` (`auto|context|chart|off`).
   - `ENABLE_CHART_IMAGES=true` to allow setup-chart images in `auto/chart` modes.
   - `PEXELS_API_KEY=...` for dynamic context-image search (falls back to static images if missing).
4. Strategy thresholds are externalized in `config/major_event_strategy.json`. Override path with `STRATEGY_CONFIG_PATH` in `.env` if needed.
   Live V2 now enforces this major-event policy when selecting publishable signals.
5. Run `python main.py`.
6. Run tests with `python -m unittest discover -s tests -p "test_*.py"`.
7. Run dry mode with `python main.py --dry-run --dry-run-output artifacts/dry_run`.

## Week 2 Ops Commands
- Day 11 calibration scaffold (uses mock outcomes automatically when needed):
  - `python main.py --run-calibration-job`
- Day 13 shadow run (no public posting):
  - `python main.py --shadow-run --shadow-iterations 96 --shadow-interval-seconds 900`
- Day 14 production-day report from run history:
  - `python main.py --build-production-report`

## Render Deployment (Real Use + Testing)
This repo now includes `render.yaml` for one-service deployment:
- Web service runs `python -m app.deploy_service`.
- Exposes:
  - `GET /health`
  - `GET /status`
  - `GET /runs?limit=200` (per-run history from JSONL)
  - `GET /metrics?limit=200` (aggregated run metrics)
  - operator dashboard at `/` (summary + latest 100 runs + dropped signal table)
- Runs background live cycles on schedule (`BACKGROUND_LOOP_INTERVAL_MINUTES`).
- Uses persistent disk at `/var/data` for:
  - run history
  - calibration model
  - trade state
  - rollback switch file

### Required Secrets To Set On Render
Set these in Render dashboard (Environment):
- `OPENAI_API_KEY` (required)
- `NEWS_API_KEY` (recommended)
- `ALPHA_VANTAGE_KEY` (required for technical context + execution plans)
- `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` (required for Telegram publishing)
- `FMP_API_KEY` (optional, for calendar enrichment)
- `OPERATOR_API_KEY` (strongly recommended, protects operator POST endpoints)

Optional:
- `PEXELS_API_KEY` (image search)
- X/Twitter keys if needed later

### First Deployment Test Flow
1. Deploy from `render.yaml` with `ENABLE_PUBLIC_POSTING=false`.
2. Open `/health` and `/status` and confirm service is alive.
3. Wait one scheduler interval and confirm runs appear in `/status` (`runs_total` increases).
4. Trigger manual dry ops via API:
   - `POST /run/calibration`
   - `POST /run/report`
5. Verify artifacts persisted under `/var/data` paths from status/run output.
6. When satisfied, set `ENABLE_PUBLIC_POSTING=true` and redeploy.

### Operator API (Protected By `X-Operator-Key`)
- `POST /run/live` body example: `{"publish_enabled": true}`
- `POST /run/calibration`
- `POST /run/report` body example: `{"day_utc":"2026-03-06"}`
- `POST /scheduler/pause`
- `POST /scheduler/resume`

Read-only observability endpoints:
- `GET /runs?limit=200`
- `GET /metrics?limit=200`

### Rollback Procedure
Immediate stop options:
1. Fastest: set `ENABLE_PUBLIC_POSTING=false` in Render env and redeploy.
2. File switch (if you can access service shell): create `/var/data/ROLLBACK`.
   - Remove file to re-enable after verification.
