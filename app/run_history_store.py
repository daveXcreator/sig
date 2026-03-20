from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

import requests

from app.config import (
    ENABLE_LOCAL_RUN_HISTORY,
    RUN_HISTORY_PATH,
    RUN_HISTORY_REMOTE_BACKEND,
    RUN_HISTORY_SUPABASE_TABLE,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)
from app.utils import log


def _remote_enabled() -> bool:
    return (
        RUN_HISTORY_REMOTE_BACKEND == "supabase"
        and bool(SUPABASE_URL)
        and bool(SUPABASE_SERVICE_ROLE_KEY)
    )


def _supabase_headers() -> dict[str, str]:
    token = str(SUPABASE_SERVICE_ROLE_KEY or "")
    return {
        "apikey": token,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _supabase_table_url() -> str:
    base = str(SUPABASE_URL or "").rstrip("/")
    return f"{base}/rest/v1/{RUN_HISTORY_SUPABASE_TABLE}"


def _append_local(summary: dict[str, Any]) -> None:
    path = Path(RUN_HISTORY_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(summary, sort_keys=True, default=str)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")


def _load_local(limit: int = 200) -> list[dict[str, Any]]:
    path = Path(RUN_HISTORY_PATH)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    selected = lines[-max(1, int(limit)) :]
    runs: list[dict[str, Any]] = []
    for line in reversed(selected):
        row = line.strip()
        if not row:
            continue
        try:
            parsed = json.loads(row)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            runs.append(parsed)
    return runs


def _load_local_for_day(target_day: str) -> list[dict[str, Any]]:
    path = Path(RUN_HISTORY_PATH)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    filtered: list[dict[str, Any]] = []
    for line in lines:
        row = line.strip()
        if not row:
            continue
        try:
            parsed = json.loads(row)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        finished_at = str(parsed.get("finished_at", ""))
        if finished_at.startswith(f"{target_day}T"):
            filtered.append(parsed)
    return filtered


def _append_remote(summary: dict[str, Any]) -> None:
    payload = {
        "run_id": summary.get("run_id"),
        "finished_at": summary.get("finished_at"),
        "status": summary.get("status"),
        "reason": summary.get("reason"),
        "summary": summary,
    }
    response = requests.post(
        f"{_supabase_table_url()}?on_conflict=run_id",
        headers={
            **_supabase_headers(),
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        json=[payload],
        timeout=20,
    )
    response.raise_for_status()


def _extract_remote_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    extracted: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        summary = row.get("summary")
        if isinstance(summary, dict):
            extracted.append(summary)
    return extracted


def _load_remote(limit: int = 200) -> list[dict[str, Any]]:
    response = requests.get(
        f"{_supabase_table_url()}?select=summary&order=finished_at.desc&limit={max(1, int(limit))}",
        headers=_supabase_headers(),
        timeout=20,
    )
    response.raise_for_status()
    return _extract_remote_rows(response.json())


def _load_remote_for_day(target_day: str) -> list[dict[str, Any]]:
    day_start = datetime.fromisoformat(f"{target_day}T00:00:00+00:00")
    next_day = day_start + timedelta(days=1)
    response = requests.get(
        (
            f"{_supabase_table_url()}?select=summary"
            f"&finished_at=gte.{day_start.isoformat().replace('+00:00', 'Z')}"
            f"&finished_at=lt.{next_day.isoformat().replace('+00:00', 'Z')}"
            "&order=finished_at.asc&limit=5000"
        ),
        headers=_supabase_headers(),
        timeout=20,
    )
    response.raise_for_status()
    return _extract_remote_rows(response.json())


def append_run_history(summary: dict[str, Any]) -> None:
    remote_ok = False
    if _remote_enabled():
        try:
            _append_remote(summary)
            remote_ok = True
        except requests.RequestException as err:
            log(f"Remote run history write failed: {err}")
    if ENABLE_LOCAL_RUN_HISTORY:
        try:
            _append_local(summary)
        except OSError as err:
            log(f"Local run history write failed: {err}")
    elif not remote_ok:
        log("Run history not persisted: remote disabled/failed and local history disabled.")


def load_recent_run_history(limit: int = 200) -> list[dict[str, Any]]:
    if _remote_enabled():
        try:
            rows = _load_remote(limit=limit)
            if rows:
                return rows
        except requests.RequestException as err:
            log(f"Remote run history load failed: {err}")
    if ENABLE_LOCAL_RUN_HISTORY:
        return _load_local(limit=limit)
    return []


def load_run_history_for_day(target_day: str) -> list[dict[str, Any]]:
    if _remote_enabled():
        try:
            rows = _load_remote_for_day(target_day)
            if rows:
                return rows
        except requests.RequestException as err:
            log(f"Remote day history load failed: {err}")
    if ENABLE_LOCAL_RUN_HISTORY:
        return _load_local_for_day(target_day)
    return []


def run_history_backend_label() -> str:
    if _remote_enabled():
        return f"supabase:{RUN_HISTORY_SUPABASE_TABLE}"
    if ENABLE_LOCAL_RUN_HISTORY:
        return f"local:{RUN_HISTORY_PATH}"
    return "memory_only"
