from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from app.config import TRADE_STATE_PATH
from app.signal_setup import AlphaVantageIntradayProvider, SignalExecutionPlan

STATE_PATH = Path(TRADE_STATE_PATH)
ACTIVE_STATES = {"PENDING", "TRIGGERED"}
TERMINAL_STATES = {"CLOSED_PROFIT", "INVALIDATED", "EXPIRED"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso8601_utc(value: str) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(slots=True)
class TrackedTrade:
    signal_id: str
    pair: str
    direction: str
    state: str
    created_at: str
    valid_until: str
    entry_trigger_price: float
    risk_line_price: float
    entry_price: float | None = None
    triggered_at: str | None = None
    closed_at: str | None = None
    result_r_multiple: float | None = None


@dataclass(slots=True)
class TradeUpdate:
    signal_id: str
    pair: str
    state: str
    result_r_multiple: float | None
    message: str


def format_trade_result_update(update: TradeUpdate) -> str:
    if update.state == "CLOSED_PROFIT":
        status = "Closed in profit"
        outcome = f"+{update.result_r_multiple:.2f}R" if update.result_r_multiple is not None else "profit"
        what = "Setup triggered and momentum reached target."
    elif update.state == "INVALIDATED":
        status = "Invalidated"
        outcome = f"{update.result_r_multiple:.2f}R" if update.result_r_multiple is not None else "loss"
        what = "Price moved against setup and hit risk line."
    else:
        status = "Expired"
        outcome = "no trigger"
        what = "Setup validity ended before a clean trigger."

    return (
        "*Signalyze AI Result*\n\n"
        f"*Pair:* {update.pair}\n"
        f"*Status:* {status}\n"
        f"*Outcome:* {outcome}\n"
        f"*What Happened:* {what}\n"
    )


class TradeTracker:
    def __init__(self, state_path: Path = STATE_PATH):
        self.state_path = state_path

    def _load(self) -> dict[str, TrackedTrade]:
        if not self.state_path.exists():
            return {}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        rows = payload.get("trades", [])
        trades: dict[str, TrackedTrade] = {}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                trade = TrackedTrade(
                    signal_id=str(row["signal_id"]),
                    pair=str(row["pair"]),
                    direction=str(row["direction"]),
                    state=str(row["state"]),
                    created_at=str(row["created_at"]),
                    valid_until=str(row["valid_until"]),
                    entry_trigger_price=float(row["entry_trigger_price"]),
                    risk_line_price=float(row["risk_line_price"]),
                    entry_price=float(row["entry_price"]) if row.get("entry_price") is not None else None,
                    triggered_at=str(row["triggered_at"]) if row.get("triggered_at") else None,
                    closed_at=str(row["closed_at"]) if row.get("closed_at") else None,
                    result_r_multiple=float(row["result_r_multiple"]) if row.get("result_r_multiple") is not None else None,
                )
            except Exception:
                continue
            trades[trade.signal_id] = trade
        return trades

    def _save(self, trades: dict[str, TrackedTrade]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"trades": [asdict(trade) for trade in trades.values()]}
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def register_new_plans(self, plans: dict[str, SignalExecutionPlan]) -> int:
        trades = self._load()
        added = 0
        for signal_id, plan in plans.items():
            existing = trades.get(signal_id)
            if existing and existing.state in ACTIVE_STATES.union(TERMINAL_STATES):
                continue
            trades[signal_id] = TrackedTrade(
                signal_id=signal_id,
                pair=plan.pair,
                direction=plan.direction,
                state="PENDING",
                created_at=_now_utc().isoformat().replace("+00:00", "Z"),
                valid_until=plan.valid_until,
                entry_trigger_price=plan.entry_trigger_price,
                risk_line_price=plan.risk_line_price,
            )
            added += 1
        self._save(trades)
        return added

    def evaluate_open_trades(self, intraday_provider: AlphaVantageIntradayProvider) -> list[TradeUpdate]:
        trades = self._load()
        now = _now_utc()
        updates: list[TradeUpdate] = []

        for trade in trades.values():
            if trade.state not in ACTIVE_STATES:
                continue

            valid_until = _parse_iso8601_utc(trade.valid_until)
            latest_close = intraday_provider.get_latest_close(trade.pair)
            if latest_close is None:
                continue

            if trade.state == "PENDING":
                if valid_until is not None and now > valid_until:
                    trade.state = "EXPIRED"
                    trade.closed_at = now.isoformat().replace("+00:00", "Z")
                    updates.append(
                        TradeUpdate(
                            signal_id=trade.signal_id,
                            pair=trade.pair,
                            state=trade.state,
                            result_r_multiple=None,
                            message="expired",
                        )
                    )
                    continue

                if trade.direction == "bullish" and latest_close >= trade.entry_trigger_price:
                    trade.state = "TRIGGERED"
                    trade.entry_price = latest_close
                    trade.triggered_at = now.isoformat().replace("+00:00", "Z")
                elif trade.direction == "bearish" and latest_close <= trade.entry_trigger_price:
                    trade.state = "TRIGGERED"
                    trade.entry_price = latest_close
                    trade.triggered_at = now.isoformat().replace("+00:00", "Z")

            if trade.state == "TRIGGERED" and trade.entry_price is not None:
                risk_distance = abs(trade.entry_price - trade.risk_line_price)
                if risk_distance <= 0:
                    continue
                if trade.direction == "bullish":
                    target_price = trade.entry_price + risk_distance
                    hit_invalid = latest_close <= trade.risk_line_price
                    hit_profit = latest_close >= target_price
                else:
                    target_price = trade.entry_price - risk_distance
                    hit_invalid = latest_close >= trade.risk_line_price
                    hit_profit = latest_close <= target_price

                if hit_invalid:
                    trade.state = "INVALIDATED"
                    trade.closed_at = now.isoformat().replace("+00:00", "Z")
                    trade.result_r_multiple = -1.0
                    updates.append(
                        TradeUpdate(
                            signal_id=trade.signal_id,
                            pair=trade.pair,
                            state=trade.state,
                            result_r_multiple=trade.result_r_multiple,
                            message="invalidated",
                        )
                    )
                elif hit_profit:
                    trade.state = "CLOSED_PROFIT"
                    trade.closed_at = now.isoformat().replace("+00:00", "Z")
                    trade.result_r_multiple = 1.0
                    updates.append(
                        TradeUpdate(
                            signal_id=trade.signal_id,
                            pair=trade.pair,
                            state=trade.state,
                            result_r_multiple=trade.result_r_multiple,
                            message="closed_profit",
                        )
                    )

        self._save(trades)
        return updates

    def count_active(self) -> int:
        trades = self._load()
        return sum(1 for trade in trades.values() if trade.state in ACTIVE_STATES)
