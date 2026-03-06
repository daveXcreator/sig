# Render Deployment Runbook

## 1) Deploy
1. Push this repo to GitHub.
2. In Render, create a Blueprint deploy from repo root (uses `render.yaml`).
3. Confirm service starts and `/health` returns `{"status":"ok"}`.

## 2) Set Environment Secrets
Required:
- `OPENAI_API_KEY`
- `ALPHA_VANTAGE_KEY`
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`
- `OPERATOR_API_KEY`

Recommended:
- `NEWS_API_KEY`
- `FMP_API_KEY`
- `PEXELS_API_KEY` (if images enabled)

## 3) Safe Start (Testing Mode)
Use:
- `ENABLE_PUBLIC_POSTING=false`
- `ENABLE_BACKGROUND_LOOP=true`
- `BACKGROUND_LOOP_INTERVAL_MINUTES=15`

Then validate:
1. `GET /status` shows scheduler running.
2. `runs_total` increases over time.
3. `publish_stats.telegram` remains `0` during testing mode.
4. `GET /runs?limit=50` returns recent run history records.
5. `GET /metrics?limit=50` returns aggregate quality/latency stats.

## 4) Operator Calls
All `POST` requests must include header:
- `X-Operator-Key: <OPERATOR_API_KEY>`

Endpoints:
- `POST /run/live` optional body `{ "publish_enabled": true }`
- `POST /run/calibration`
- `POST /run/report` optional body `{ "day_utc": "YYYY-MM-DD" }`
- `POST /scheduler/pause`
- `POST /scheduler/resume`

Observability:
- `GET /dashboard` (or `/`) shows summary cards + latest 100 runs.
- `GET /runs?limit=200` returns per-run history JSON.
- `GET /metrics?limit=200` returns aggregate run metrics JSON.

## 5) Go Live
1. Set `ENABLE_PUBLIC_POSTING=true`.
2. Redeploy.
3. Watch `/status`:
- `runs_ok` should increase.
- `publish_guardrail_reason` should be `null` on healthy runs.

## 6) Emergency Rollback
Option A:
- Set `ENABLE_PUBLIC_POSTING=false` and redeploy.

Option B:
- Activate rollback file at configured path (`ROLLBACK_SWITCH_FILE`, default `/var/data/ROLLBACK`).
- Remove the file only after issue is verified fixed.

## 7) Daily Ops
1. Check `/status`.
2. Trigger `POST /run/report` once daily.
3. Trigger `POST /run/calibration` daily/weekly depending on outcomes volume.
