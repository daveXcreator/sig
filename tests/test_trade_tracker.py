from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from app.signal_setup import SignalExecutionPlan
from app.trade_tracker import TradeTracker


class _PriceStub:
    def __init__(self, prices: list[float | None]):
        self._prices = prices
        self._idx = 0

    def get_latest_close(self, pair: str) -> float | None:
        _ = pair
        if self._idx >= len(self._prices):
            return self._prices[-1]
        value = self._prices[self._idx]
        self._idx += 1
        return value


class TradeTrackerTests(unittest.TestCase):
    @patch("app.trade_tracker.ENABLE_TRADE_TRACKING", False)
    def test_tracking_can_be_disabled(self):
        tracker = TradeTracker(state_path=Path("artifacts") / "disabled_trade_state.json")
        plan = SignalExecutionPlan(
            signal_id="sig_disabled",
            pair="USD/JPY",
            direction="bullish",
            entry_trigger_price=150.00,
            risk_line_price=149.00,
            valid_for_hours=6,
            valid_until="2099-01-01T00:00:00Z",
            when_to_enter="Enter on close above 150.00",
            risk_line_text="Exit below 149.00",
            volatility_bucket="normal",
        )

        self.assertEqual(0, tracker.register_new_plans({"sig_disabled": plan}))
        self.assertEqual([], tracker.evaluate_open_trades(_PriceStub([150.05])))
        self.assertEqual(0, tracker.count_active())

    @patch("app.trade_tracker.ENABLE_TRADE_TRACKING", True)
    def test_register_and_close_profit_trade(self):
        out_dir = Path("artifacts") / f"test_trade_tracker_{uuid.uuid4().hex}"
        out_dir.mkdir(parents=True, exist_ok=True)
        state_path = out_dir / "trade_state.json"

        try:
            tracker = TradeTracker(state_path=state_path)
            plan = SignalExecutionPlan(
                signal_id="sig_1",
                pair="USD/JPY",
                direction="bullish",
                entry_trigger_price=150.00,
                risk_line_price=149.00,
                valid_for_hours=6,
                valid_until="2099-01-01T00:00:00Z",
                when_to_enter="Enter on close above 150.00",
                risk_line_text="Exit below 149.00",
                volatility_bucket="normal",
            )
            added = tracker.register_new_plans({"sig_1": plan})
            self.assertEqual(1, added)
            self.assertEqual(1, tracker.count_active())

            # First pass triggers entry, second pass closes in profit (+1R target at 151.00).
            updates_first = tracker.evaluate_open_trades(_PriceStub([150.05]))
            self.assertEqual([], updates_first)
            updates_second = tracker.evaluate_open_trades(_PriceStub([151.20]))
            self.assertEqual(1, len(updates_second))
            self.assertEqual("CLOSED_PROFIT", updates_second[0].state)
            self.assertEqual(1.0, updates_second[0].result_r_multiple)
            self.assertEqual(0, tracker.count_active())
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
