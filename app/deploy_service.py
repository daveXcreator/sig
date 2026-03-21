from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from app.config import (
    BACKGROUND_LOOP_INTERVAL_MINUTES,
    ENABLE_BACKGROUND_LOOP,
    OPERATOR_API_KEY,
)
from app.confidence_calibration import run_calibration_job
from app.launch_report import build_production_day_report
from app.run_history_store import load_recent_run_history, run_history_backend_label
from app.unified_pipeline import run_live_v2
from app.utils import log


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _format_utc_display(value: Any) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        dt = value.astimezone(timezone.utc)
    else:
        text = str(value).strip()
        if not text:
            return "-"
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return text
    return dt.strftime("%a %d %b %Y, %H:%M UTC")


def _env_port(default: int = 10000) -> int:
    import os

    raw = os.getenv("PORT")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


_state_lock = threading.Lock()
_action_lock = threading.Lock()
_stop_event = threading.Event()
_recent_runs: list[dict[str, Any]] = []

_state: dict[str, Any] = {
    "started_at": _utc_now_iso(),
    "scheduler_enabled": ENABLE_BACKGROUND_LOOP,
    "scheduler_paused": False,
    "interval_minutes": float(BACKGROUND_LOOP_INTERVAL_MINUTES),
    "run_in_progress": False,
    "runs_total": 0,
    "runs_ok": 0,
    "runs_failed": 0,
    "last_run_started_at": None,
    "last_run_finished_at": None,
    "last_run_trigger": None,
    "last_run_summary": None,
    "last_error": None,
    "action_in_progress": False,
    "last_action": None,
}


def _snapshot() -> dict[str, Any]:
    with _state_lock:
        return json.loads(json.dumps(_state, default=str))


def _set_state(**fields: Any) -> None:
    with _state_lock:
        _state.update(fields)


def _run_live_once(trigger: str, publish_enabled: bool = True) -> dict[str, Any] | None:
    with _state_lock:
        if _state.get("run_in_progress"):
            return None
        _state["run_in_progress"] = True
        _state["last_run_started_at"] = _utc_now_iso()
        _state["last_run_trigger"] = trigger

    try:
        summary = run_live_v2(enable_x=False, publish_enabled=publish_enabled)
    except Exception as err:
        _set_state(
            run_in_progress=False,
            runs_total=int(_snapshot().get("runs_total", 0)) + 1,
            runs_failed=int(_snapshot().get("runs_failed", 0)) + 1,
            last_error=f"{type(err).__name__}: {err}",
            last_run_finished_at=_utc_now_iso(),
        )
        log(f"Live run crashed ({trigger}): {err}")
        return {
            "status": "failed",
            "reason": f"exception:{type(err).__name__}",
            "error": str(err),
        }

    status = str(summary.get("status", "unknown"))
    runs = _snapshot()
    _remember_run(summary)
    _set_state(
        run_in_progress=False,
        runs_total=int(runs.get("runs_total", 0)) + 1,
        runs_ok=int(runs.get("runs_ok", 0)) + (1 if status == "ok" else 0),
        runs_failed=int(runs.get("runs_failed", 0)) + (0 if status == "ok" else 1),
        last_run_summary=summary,
        last_error=None if status == "ok" else summary.get("reason"),
        last_run_finished_at=_utc_now_iso(),
    )
    return summary


def _remember_run(summary: dict[str, Any]) -> None:
    _recent_runs.insert(0, json.loads(json.dumps(summary, default=str)))
    del _recent_runs[300:]


def _start_action(name: str, fn: Callable[..., Any], **kwargs: Any) -> tuple[bool, dict[str, Any]]:
    with _action_lock:
        if _snapshot().get("action_in_progress"):
            return False, {"status": "busy", "message": "another action is running"}
        _set_state(
            action_in_progress=True,
            last_action={
                "name": name,
                "started_at": _utc_now_iso(),
                "status": "running",
                "result": None,
            },
        )

    def _runner() -> None:
        try:
            result = fn(**kwargs)
            status = "ok"
        except Exception as err:
            result = {"status": "failed", "reason": f"exception:{type(err).__name__}", "error": str(err)}
            status = "failed"
        _set_state(
            action_in_progress=False,
            last_action={
                "name": name,
                "started_at": _snapshot().get("last_action", {}).get("started_at"),
                "finished_at": _utc_now_iso(),
                "status": status,
                "result": result,
            },
        )

    thread = threading.Thread(target=_runner, daemon=True, name=f"action-{name}")
    thread.start()
    return True, {"status": "accepted", "action": name}


def _background_loop() -> None:
    interval_seconds = max(30.0, float(BACKGROUND_LOOP_INTERVAL_MINUTES) * 60.0)
    log(
        "Background live loop started "
        f"(interval_minutes={BACKGROUND_LOOP_INTERVAL_MINUTES})."
    )
    while not _stop_event.is_set():
        snapshot = _snapshot()
        if not snapshot.get("scheduler_paused", False):
            _run_live_once(trigger="scheduled", publish_enabled=True)
        _stop_event.wait(interval_seconds)


def _auth_ok(handler: BaseHTTPRequestHandler) -> bool:
    if not OPERATOR_API_KEY:
        return True
    provided = handler.headers.get("X-Operator-Key", "")
    return provided == OPERATOR_API_KEY


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        length = 0
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_recent_runs(limit: int = 200) -> list[dict[str, Any]]:
    runs = load_recent_run_history(limit=limit)
    if runs:
        return runs
    return _recent_runs[: max(1, int(limit))]


def _run_metrics(runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not runs:
        return {
            "runs": 0,
            "ok_runs": 0,
            "failed_runs": 0,
            "published_signals_total": 0,
            "publishable_signals_total": 0,
            "policy_published_total": 0,
            "avg_total_latency_ms": 0.0,
            "hard_gate_failures_total": 0,
            "hard_gate_failures_breakdown": {},
            "signal_drops_total": 0,
            "signal_drop_stage_breakdown": {},
            "last_finished_at": None,
        }
    ok_runs = sum(1 for run in runs if str(run.get("status")) == "ok")
    failed_runs = sum(1 for run in runs if str(run.get("status")) != "ok")
    published_signals_total = sum(
        _safe_int((run.get("publish_stats") or {}).get("telegram"), 0)
        for run in runs
    )
    publishable_signals_total = sum(_safe_int(run.get("publishable_signals"), 0) for run in runs)
    policy_published_total = sum(_safe_int(run.get("policy_published"), 0) for run in runs)
    avg_total_latency_ms = (
        sum(_safe_float(run.get("total_latency_ms"), 0.0) for run in runs) / len(runs)
    )
    hard_gate_failures_total = sum(_safe_int(run.get("policy_failed_hard_gate"), 0) for run in runs)
    hard_gate_failures_breakdown: dict[str, int] = {}
    signal_drops_total = sum(_safe_int(run.get("signal_drop_total"), 0) for run in runs)
    signal_drop_stage_breakdown: dict[str, int] = {}
    for run in runs:
        raw = run.get("policy_failed_hard_gate_breakdown")
        if not isinstance(raw, dict):
            raw = {}
        for reason, count in raw.items():
            if isinstance(reason, str):
                hard_gate_failures_breakdown[reason] = (
                    hard_gate_failures_breakdown.get(reason, 0) + _safe_int(count, 0)
                )

        drop_counts = run.get("signal_drop_counts")
        if not isinstance(drop_counts, dict):
            drop_counts = {}
        for stage, count in drop_counts.items():
            if isinstance(stage, str):
                signal_drop_stage_breakdown[stage] = (
                    signal_drop_stage_breakdown.get(stage, 0) + _safe_int(count, 0)
                )
    return {
        "runs": len(runs),
        "ok_runs": ok_runs,
        "failed_runs": failed_runs,
        "published_signals_total": published_signals_total,
        "publishable_signals_total": publishable_signals_total,
        "policy_published_total": policy_published_total,
        "avg_total_latency_ms": round(avg_total_latency_ms, 2),
        "hard_gate_failures_total": hard_gate_failures_total,
        "hard_gate_failures_breakdown": dict(
            sorted(
                hard_gate_failures_breakdown.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "signal_drops_total": signal_drops_total,
        "signal_drop_stage_breakdown": dict(
            sorted(
                signal_drop_stage_breakdown.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "last_finished_at": runs[0].get("finished_at"),
    }


def _collect_recent_signal_drops(
    runs: list[dict[str, Any]], limit: int = 120
) -> list[dict[str, Any]]:
    drops: list[dict[str, Any]] = []
    for run in runs:
        run_id = run.get("run_id")
        finished_at = run.get("finished_at")
        details = run.get("signal_drop_details")
        if not isinstance(details, list):
            continue
        for item in details:
            if not isinstance(item, dict):
                continue
            drops.append(
                {
                    "finished_at": finished_at,
                    "run_id": run_id,
                    "stage": item.get("stage"),
                    "reason": item.get("reason"),
                    "pair": item.get("pair"),
                    "signal_id": item.get("signal_id"),
                }
            )
            if len(drops) >= limit:
                return drops
    return drops


def _fmt_latency_ms(value: Any) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return "-"


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def _html_dashboard() -> str:
    snapshot = _snapshot()
    runs = _load_recent_runs(limit=200)
    metrics = _run_metrics(runs)
    last_run = snapshot.get("last_run_summary") or {}
    publish_stats = last_run.get("publish_stats", {}) if isinstance(last_run, dict) else {}
    last_run_started = _format_utc_display(snapshot.get("last_run_started_at"))
    last_run_finished = _format_utc_display(snapshot.get("last_run_finished_at"))
    last_finished_metric = _format_utc_display(metrics.get("last_finished_at"))
    hard_gate_breakdown = metrics.get("hard_gate_failures_breakdown", {})
    signal_drop_breakdown = metrics.get("signal_drop_stage_breakdown", {})
    recent_drops = _collect_recent_signal_drops(runs, limit=120)
    rows_html = []
    for run in runs[:100]:
        run_id = run.get("run_id", "")
        rows_html.append(
            "<tr>"
            f"<td>{_format_utc_display(run.get('finished_at'))}</td>"
            f"<td>{run.get('status', '-')}</td>"
            f"<td>{run_id[-8:] if isinstance(run_id, str) else '-'}</td>"
            f"<td>{_fmt_int(run.get('articles'))}</td>"
            f"<td>{_fmt_int(run.get('publishable_signals'))}</td>"
            f"<td>{_fmt_int((run.get('publish_stats') or {}).get('telegram'))}</td>"
            f"<td>{_fmt_int(run.get('policy_failed_hard_gate'))}</td>"
            f"<td>{_fmt_latency_ms(run.get('total_latency_ms'))}</td>"
            "</tr>"
        )
    run_rows = "\n".join(rows_html) if rows_html else "<tr><td colspan='8'>No runs yet</td></tr>"
    hard_gate_rows = []
    if isinstance(hard_gate_breakdown, dict):
        for reason, count in hard_gate_breakdown.items():
            hard_gate_rows.append(
                "<tr>"
                f"<td>{reason}</td>"
                f"<td>{_fmt_int(count)}</td>"
                "</tr>"
            )
    hard_gate_breakdown_rows = (
        "\n".join(hard_gate_rows)
        if hard_gate_rows
        else "<tr><td colspan='2'>No hard-gate failures in loaded runs</td></tr>"
    )
    drop_breakdown_rows = []
    if isinstance(signal_drop_breakdown, dict):
        for stage, count in signal_drop_breakdown.items():
            drop_breakdown_rows.append(
                "<tr>"
                f"<td>{stage}</td>"
                f"<td>{_fmt_int(count)}</td>"
                "</tr>"
            )
    signal_drop_breakdown_rows = (
        "\n".join(drop_breakdown_rows)
        if drop_breakdown_rows
        else "<tr><td colspan='2'>No dropped signals in loaded runs</td></tr>"
    )
    drop_rows = []
    for item in recent_drops:
        run_id = item.get("run_id", "")
        signal_id = item.get("signal_id", "")
        drop_rows.append(
            "<tr>"
            f"<td>{_format_utc_display(item.get('finished_at'))}</td>"
            f"<td>{run_id[-8:] if isinstance(run_id, str) else '-'}</td>"
            f"<td>{item.get('stage', '-')}</td>"
            f"<td>{item.get('reason', '-')}</td>"
            f"<td>{item.get('pair', '-')}</td>"
            f"<td>{signal_id if isinstance(signal_id, str) else '-'}</td>"
            "</tr>"
        )
    recent_drop_rows = (
        "\n".join(drop_rows)
        if drop_rows
        else "<tr><td colspan='6'>No dropped signals in loaded runs</td></tr>"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Signalyze Operator</title>
  <meta http-equiv="refresh" content="20">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    body {{ font-family: "Space Grotesk", Arial, sans-serif; margin: 24px; background: #f4f6f8; color: #111; }}
    .card {{ background: #fff; border-radius: 10px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
    h1 {{ margin-top: 0; }}
    h2 {{ margin: 8px 0; }}
    code {{ background: #eee; padding: 2px 6px; border-radius: 4px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 8px; border-bottom: 1px solid #e5e7eb; text-align: left; }}
    th {{ background: #f8fafc; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; }}
    .metric {{ background: #f8fafc; border-radius: 8px; padding: 10px; }}
    .metric .label {{ font-size: 12px; color: #555; }}
    .metric .value {{ font-size: 20px; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>Signalyze Operator</h1>
  <div class="card">
    <strong>Status:</strong> {"running" if not snapshot.get("run_in_progress") else "busy"}<br>
    <strong>Scheduler enabled:</strong> {snapshot.get("scheduler_enabled")}<br>
    <strong>Scheduler paused:</strong> {snapshot.get("scheduler_paused")}<br>
    <strong>Interval (min):</strong> {snapshot.get("interval_minutes")}<br>
    <strong>Runs:</strong> total={snapshot.get("runs_total")} ok={snapshot.get("runs_ok")} failed={snapshot.get("runs_failed")}
  </div>
  <div class="card">
    <strong>Last Run Trigger:</strong> {snapshot.get("last_run_trigger")}<br>
    <strong>Last Run Started:</strong> {last_run_started}<br>
    <strong>Last Run Finished:</strong> {last_run_finished}<br>
    <strong>Published:</strong> telegram={publish_stats.get("telegram", 0)} results={publish_stats.get("results", 0)}<br>
    <strong>Guardrail:</strong> {last_run.get("publish_guardrail_reason")}<br>
  </div>
  <div class="card">
    <h2>Recent Run Metrics (from run history)</h2>
    <div class="metrics">
      <div class="metric"><div class="label">Runs (loaded)</div><div class="value">{metrics.get("runs")}</div></div>
      <div class="metric"><div class="label">OK / Failed</div><div class="value">{metrics.get("ok_runs")} / {metrics.get("failed_runs")}</div></div>
      <div class="metric"><div class="label">Published (Telegram)</div><div class="value">{metrics.get("published_signals_total")}</div></div>
      <div class="metric"><div class="label">Publishable Signals</div><div class="value">{metrics.get("publishable_signals_total")}</div></div>
      <div class="metric"><div class="label">Policy Published</div><div class="value">{metrics.get("policy_published_total")}</div></div>
      <div class="metric"><div class="label">Hard Gate Failures</div><div class="value">{metrics.get("hard_gate_failures_total")}</div></div>
      <div class="metric"><div class="label">Signal Drops</div><div class="value">{metrics.get("signal_drops_total")}</div></div>
      <div class="metric"><div class="label">Avg Latency (ms)</div><div class="value">{metrics.get("avg_total_latency_ms")}</div></div>
      <div class="metric"><div class="label">Last Finished</div><div class="value" style="font-size:12px">{last_finished_metric}</div></div>
    </div>
  </div>
  <div class="card">
    <h2>Hard Gate Reason Breakdown</h2>
    <table>
      <thead>
        <tr>
          <th>Reason</th>
          <th>Count</th>
        </tr>
      </thead>
      <tbody>
        {hard_gate_breakdown_rows}
      </tbody>
    </table>
  </div>
  <div class="card">
    <h2>Signal Drop Stage Breakdown</h2>
    <table>
      <thead>
        <tr>
          <th>Stage</th>
          <th>Count</th>
        </tr>
      </thead>
      <tbody>
        {signal_drop_breakdown_rows}
      </tbody>
    </table>
  </div>
  <div class="card">
    <h2>Dropped Signals (latest 120)</h2>
    <table>
      <thead>
        <tr>
          <th>Finished</th>
          <th>Run</th>
          <th>Stage</th>
          <th>Reason</th>
          <th>Pair</th>
          <th>Signal ID</th>
        </tr>
      </thead>
      <tbody>
        {recent_drop_rows}
      </tbody>
    </table>
  </div>
  <div class="card">
    <h2>Run History (latest 100)</h2>
    <table>
      <thead>
        <tr>
          <th>Finished</th>
          <th>Status</th>
          <th>Run</th>
          <th>Articles</th>
          <th>Publishable</th>
          <th>Posted</th>
          <th>HardGateFail</th>
          <th>Latency ms</th>
        </tr>
      </thead>
      <tbody>
        {run_rows}
      </tbody>
    </table>
  </div>
  <div class="card">
    <p>API endpoints:</p>
    <p><code>GET /health</code>, <code>GET /status</code>, <code>GET /runs?limit=200</code>, <code>GET /metrics?limit=200</code></p>
    <p><code>POST /run/live</code>, <code>POST /run/calibration</code>, <code>POST /run/report</code></p>
    <p><code>POST /scheduler/pause</code>, <code>POST /scheduler/resume</code></p>
  </div>
</body>
</html>
"""


class OperatorHandler(BaseHTTPRequestHandler):
    server_version = "SignalyzeOperator/1.0"

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_html(self, status: int, html_text: str) -> None:
        body = html_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/health":
            self._write_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "service": "signalyze-operator",
                    "ts": _utc_now_iso(),
                },
            )
            return
        if path == "/status":
            self._write_json(HTTPStatus.OK, _snapshot())
            return
        if path == "/runs":
            limit = _safe_int((query.get("limit") or [200])[0], 200)
            limit = max(1, min(2000, limit))
            runs = _load_recent_runs(limit=limit)
            self._write_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "count": len(runs),
                    "limit": limit,
                    "path": run_history_backend_label(),
                    "runs": runs,
                },
            )
            return
        if path == "/metrics":
            limit = _safe_int((query.get("limit") or [200])[0], 200)
            limit = max(1, min(2000, limit))
            runs = _load_recent_runs(limit=limit)
            metrics = _run_metrics(runs)
            self._write_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "limit": limit,
                    "metrics": metrics,
                },
            )
            return
        if path in {"/", "/dashboard"}:
            self._write_html(HTTPStatus.OK, _html_dashboard())
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"status": "not_found"})

    def do_POST(self) -> None:
        if not _auth_ok(self):
            self._write_json(HTTPStatus.UNAUTHORIZED, {"status": "unauthorized"})
            return
        payload = _read_json_body(self)

        if self.path == "/run/live":
            publish_enabled = _coerce_bool(payload.get("publish_enabled", True), default=True)
            accepted, result = _start_action(
                "run_live",
                _run_live_once,
                trigger="manual",
                publish_enabled=publish_enabled,
            )
            code = HTTPStatus.ACCEPTED if accepted else HTTPStatus.CONFLICT
            self._write_json(code, result)
            return

        if self.path == "/run/calibration":
            accepted, result = _start_action(
                "run_calibration",
                run_calibration_job,
            )
            code = HTTPStatus.ACCEPTED if accepted else HTTPStatus.CONFLICT
            self._write_json(code, result)
            return

        if self.path == "/run/report":
            day_utc = payload.get("day_utc")
            accepted, result = _start_action(
                "run_report",
                build_production_day_report,
                day_utc=day_utc if isinstance(day_utc, str) and day_utc.strip() else None,
            )
            code = HTTPStatus.ACCEPTED if accepted else HTTPStatus.CONFLICT
            self._write_json(code, result)
            return

        if self.path == "/scheduler/pause":
            _set_state(scheduler_paused=True)
            self._write_json(HTTPStatus.OK, {"status": "ok", "scheduler_paused": True})
            return

        if self.path == "/scheduler/resume":
            _set_state(scheduler_paused=False)
            self._write_json(HTTPStatus.OK, {"status": "ok", "scheduler_paused": False})
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"status": "not_found"})

    def log_message(self, format: str, *args: Any) -> None:
        log(f"operator_http {self.client_address[0]} - {format % args}")


def serve() -> None:
    port = _env_port(default=10000)
    server = ThreadingHTTPServer(("0.0.0.0", port), OperatorHandler)
    if ENABLE_BACKGROUND_LOOP:
        loop_thread = threading.Thread(target=_background_loop, daemon=True, name="live-loop")
        loop_thread.start()
    if not OPERATOR_API_KEY:
        log("OPERATOR_API_KEY is not set; operator POST endpoints are unsecured.")
    log(f"Operator service listening on 0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _stop_event.set()
        server.server_close()


if __name__ == "__main__":
    serve()
