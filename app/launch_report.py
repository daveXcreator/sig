from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.config import RUN_HISTORY_PATH
from app.utils import log


def _utc_date(value: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date().isoformat()


def _load_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries


def _next_actions(summary: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if summary["failed_runs"] > 0:
        actions.append("Investigate failed runs and patch top failure reasons before scaling cadence.")
    if summary["signals_published"] == 0:
        actions.append("Review policy thresholds and data coverage; no signals were published today.")
    if summary["guardrail_blocks"] > 0:
        actions.append("Guardrail blocked publishing at least once; review rollback/safety flags and intent.")
    if summary["calendar_events_total"] == 0:
        actions.append("Calendar enrichment returned zero events; verify provider/API settings.")
    if not actions:
        actions.append("Keep current settings and monitor another day before threshold changes.")
    return actions


def build_production_day_report(
    *,
    day_utc: str | None = None,
    history_path: str | Path = RUN_HISTORY_PATH,
    output_dir: str = "artifacts/live/reports",
) -> dict[str, Any]:
    target_day = day_utc or datetime.now(timezone.utc).date().isoformat()
    history = _load_history(Path(history_path))
    filtered = [row for row in history if _utc_date(row.get("finished_at")) == target_day]

    status_counter = Counter(str(row.get("status", "unknown")) for row in filtered)
    reason_counter = Counter(str(row.get("reason")) for row in filtered if row.get("reason"))

    summary = {
        "day_utc": target_day,
        "runs": len(filtered),
        "ok_runs": status_counter.get("ok", 0),
        "failed_runs": status_counter.get("failed", 0),
        "articles_total": sum(int(row.get("articles", 0) or 0) for row in filtered),
        "decisions_total": sum(int(row.get("decisions", 0) or 0) for row in filtered),
        "publish_candidates_total": sum(
            int(row.get("publish_candidate_signals", 0) or 0) for row in filtered
        ),
        "signals_published": sum(
            int((row.get("publish_stats", {}) or {}).get("telegram", 0) or 0)
            for row in filtered
        ),
        "results_posts": sum(
            int((row.get("publish_stats", {}) or {}).get("results", 0) or 0)
            for row in filtered
        ),
        "guardrail_blocks": sum(1 for row in filtered if not bool(row.get("publishing_enabled", True))),
        "calendar_events_total": sum(int(row.get("calendar_events", 0) or 0) for row in filtered),
        "top_failure_reasons": dict(reason_counter.most_common(5)),
    }
    actions = _next_actions(summary)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": summary,
        "next_tuning_actions": actions,
    }

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / f"production_day_{target_day}.json"
    md_path = root / f"production_day_{target_day}.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Signalyze AI Production Day Report",
        "",
        f"- Day (UTC): {target_day}",
        f"- Generated at (UTC): {payload['generated_at']}",
        f"- Runs: {summary['runs']} (ok={summary['ok_runs']}, failed={summary['failed_runs']})",
        f"- Articles processed: {summary['articles_total']}",
        f"- Decisions generated: {summary['decisions_total']}",
        f"- Publish candidates: {summary['publish_candidates_total']}",
        f"- Telegram signals posted: {summary['signals_published']}",
        f"- Result updates posted: {summary['results_posts']}",
        f"- Guardrail blocks: {summary['guardrail_blocks']}",
        f"- Calendar events seen: {summary['calendar_events_total']}",
        "",
        "## Top Failure Reasons",
    ]
    if summary["top_failure_reasons"]:
        for reason, count in summary["top_failure_reasons"].items():
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- none")

    lines.extend(["", "## Next Tuning Actions"])
    for action in actions:
        lines.append(f"- {action}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    payload["report_json"] = str(json_path.resolve())
    payload["report_markdown"] = str(md_path.resolve())
    log(
        "Production day report generated "
        f"(day={target_day}, runs={summary['runs']}, file={json_path})."
    )
    return payload
