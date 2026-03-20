# Free Tier Mode

Free tier mode keeps the signal engine working while reducing dependence on server disk storage.

## What Still Works
- News fetching
- OpenAI analysis
- Signal generation
- Signal gates/policy
- Telegram publishing
- Operator dashboard

## What Changes
- Run history can live only in memory unless you enable local file history.
- Trade tracking is disabled by default.
- File-based rollback is disabled by default.
- Background loop is disabled by default.

## Core Env Vars
- `FREE_TIER_MODE=true`
- `ENABLE_LOCAL_RUN_HISTORY=false`
- `ENABLE_TRADE_TRACKING=false`
- `ENABLE_FILE_ROLLBACK_SWITCH=false`
- `ENABLE_BACKGROUND_LOOP=false`

## Optional Controls
- `ROLLBACK_SWITCH_ACTIVE=true`
  - Env-based emergency stop for publishing.
- `ENABLE_PUBLIC_POSTING=false`
  - Global publish stop.

## Recommended Free-Tier Pattern
1. Host the app.
2. Keep `FREE_TIER_MODE=true`.
3. Trigger `/run/live` from an external scheduler instead of relying on a permanent background loop.
4. Use Telegram as the primary output.

## About History Reset
If you want run history to survive app restarts, yes, you need an external store.

Good long-term answer:
- external database for run history and drop history

## Easiest External DB Option
Use Supabase.

Why:
- free tier exists
- this project already has `requests`
- no heavy database driver was needed

## Env Vars For Supabase History
- `RUN_HISTORY_REMOTE_BACKEND=supabase`
- `SUPABASE_URL=https://YOUR_PROJECT.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY`
- `RUN_HISTORY_SUPABASE_TABLE=signalyze_run_history`

Keep these for free-tier mode:
- `FREE_TIER_MODE=true`
- `ENABLE_LOCAL_RUN_HISTORY=false`

## Supabase Table
Create this table in Supabase SQL editor:

```sql
create table if not exists public.signalyze_run_history (
  id bigint generated always as identity primary key,
  run_id text unique not null,
  finished_at timestamptz not null,
  status text not null,
  reason text null,
  summary jsonb not null
);

create index if not exists signalyze_run_history_finished_at_idx
on public.signalyze_run_history (finished_at desc);
```

## What This Fixes
With Supabase enabled:
- run history survives host restarts
- dashboard can reload past runs
- metrics can rebuild from stored history
- dropped-signal history survives restarts too, because it is inside each saved summary

Current code after this change:
- can run without depending on local history files
- keeps recent runs in memory for the active process
- will still lose memory when the host fully restarts unless history is moved to an external database
