from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
from typing import Any
from uuid import uuid4


def _write_line(line: str) -> None:
    if hasattr(sys.stdout, "buffer"):
        encoding = sys.stdout.encoding or "utf-8"
        sys.stdout.buffer.write(line.encode(encoding, errors="replace"))
        sys.stdout.flush()
        return
    print(line, end="")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    _write_line(f"[{timestamp}] {message}\n")


def generate_run_id(prefix: str = "run") -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}_{timestamp}_{uuid4().hex[:8]}"


def log_event(
    stage: str,
    event: str,
    *,
    run_id: str | None = None,
    signal_id: str | None = None,
    latency_ms: float | None = None,
    result: str | None = None,
    **fields: Any,
) -> None:
    payload: dict[str, Any] = {
        "event": event,
        "stage": stage,
        "ts": _utc_now_iso(),
    }
    if run_id:
        payload["run_id"] = run_id
    if signal_id:
        payload["signal_id"] = signal_id
    if latency_ms is not None:
        payload["latency_ms"] = round(float(latency_ms), 2)
    if result:
        payload["result"] = result
    for key, value in fields.items():
        if value is not None:
            payload[key] = value

    _write_line(f"{json.dumps(payload, sort_keys=True, default=str)}\n")
