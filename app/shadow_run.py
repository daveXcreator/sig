from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Callable

from app.unified_pipeline import run_live_v2
from app.utils import log


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _call_runner(runner: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    try:
        return runner(enable_x=False, publish_enabled=False)
    except TypeError:
        return runner()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Signalyze AI Shadow Run Report",
        "",
        f"- Generated at (UTC): {payload['generated_at']}",
        f"- Runs executed: {payload['runs_executed']}",
        f"- Successful runs: {payload['successful_runs']}",
        f"- Failed runs: {payload['failed_runs']}",
        f"- Decisions total: {payload['totals']['decisions']}",
        f"- Publish candidates total: {payload['totals']['publish_candidates']}",
        f"- Policy-published total: {payload['totals']['policy_published']}",
        "",
        "## Rejection Causes",
    ]
    for key, count in payload["rejection_causes"].items():
        lines.append(f"- {key}: {count}")

    lines.extend(["", "## Stability Issues"])
    if payload["stability_issues"]:
        for issue in payload["stability_issues"]:
            lines.append(f"- {issue}")
    else:
        lines.append("- none")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_shadow_session(
    *,
    iterations: int = 96,
    interval_seconds: float = 900.0,
    output_dir: str = "artifacts/shadow_run",
    runner: Callable[..., dict[str, Any]] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    run_once = runner or run_live_v2
    cycles = max(1, int(iterations))
    delay = max(0.0, float(interval_seconds))

    status_counter: Counter[str] = Counter()
    reason_counter: Counter[str] = Counter()
    rejection_counter: Counter[str] = Counter()
    totals = {
        "articles": 0,
        "impacts": 0,
        "contexts": 0,
        "decisions": 0,
        "publish_candidates": 0,
        "policy_published": 0,
    }
    run_summaries: list[dict[str, Any]] = []

    for index in range(cycles):
        started = _utc_now_iso()
        try:
            summary = _call_runner(run_once)
        except Exception as err:
            summary = {
                "status": "failed",
                "reason": f"exception:{type(err).__name__}",
                "articles": 0,
                "impacts": 0,
                "contexts": 0,
                "decisions": 0,
                "publish_candidate_signals": 0,
                "policy_published": 0,
            }

        status = str(summary.get("status", "unknown"))
        reason = str(summary.get("reason", "")) if summary.get("reason") else ""
        status_counter[status] += 1
        if reason:
            reason_counter[reason] += 1

        totals["articles"] += int(summary.get("articles", 0) or 0)
        totals["impacts"] += int(summary.get("impacts", 0) or 0)
        totals["contexts"] += int(summary.get("contexts", 0) or 0)
        totals["decisions"] += int(summary.get("decisions", 0) or 0)
        totals["publish_candidates"] += int(summary.get("publish_candidate_signals", 0) or 0)
        totals["policy_published"] += int(summary.get("policy_published", 0) or 0)

        for key, value in summary.items():
            if not key.startswith("policy_failed_"):
                continue
            try:
                count = int(value)
            except (TypeError, ValueError):
                continue
            if count > 0:
                rejection_counter[key] += count

        run_summaries.append(
            {
                "index": index + 1,
                "started_at": started,
                "status": status,
                "reason": reason or None,
                "articles": int(summary.get("articles", 0) or 0),
                "decisions": int(summary.get("decisions", 0) or 0),
                "publish_candidate_signals": int(summary.get("publish_candidate_signals", 0) or 0),
                "policy_published": int(summary.get("policy_published", 0) or 0),
            }
        )

        if index < cycles - 1 and delay > 0:
            sleep_fn(delay)

    stability_issues: list[str] = []
    failed_runs = status_counter.get("failed", 0)
    if failed_runs > 0:
        stability_issues.append(f"{failed_runs} run(s) failed during shadow mode.")
    if totals["decisions"] == 0:
        stability_issues.append("No decisions were generated across the shadow session.")
    if totals["publish_candidates"] == 0:
        stability_issues.append("No publish candidates met policy during the shadow session.")
    if totals["contexts"] == 0:
        stability_issues.append("Market context generation returned zero records.")

    report = {
        "mode": "shadow_run",
        "generated_at": _utc_now_iso(),
        "runs_executed": cycles,
        "successful_runs": status_counter.get("ok", 0),
        "failed_runs": failed_runs,
        "status_breakdown": dict(status_counter),
        "reason_breakdown": dict(reason_counter),
        "totals": totals,
        "rejection_causes": dict(sorted(rejection_counter.items(), key=lambda item: item[1], reverse=True)),
        "stability_issues": stability_issues,
        "runs": run_summaries,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(output_dir)
    json_path = root / f"shadow_report_{stamp}.json"
    md_path = root / f"shadow_report_{stamp}.md"
    _write_json(json_path, report)
    _write_markdown(md_path, report)
    report["report_json"] = str(json_path.resolve())
    report["report_markdown"] = str(md_path.resolve())
    log(
        "Shadow run completed "
        f"(runs={cycles}, failed={failed_runs}, report={json_path})."
    )
    return report
