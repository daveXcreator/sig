import unittest
from types import SimpleNamespace

from app.schemas import SignalCandidate
from app.signal_setup import HourlyCandle, build_execution_plan


def _strategy_stub() -> SimpleNamespace:
    return SimpleNamespace(
        raw={
            "volatility_buckets": {"low_max_atr_percentile": 0.33, "normal_max_atr_percentile": 0.66},
            "entry_and_risk": {
                "lookback_bars_1h": 8,
                "atr_period_1h": 14,
                "pair_multipliers": {
                    "USD/JPY": 1.1,
                    "EUR/USD": 1.0,
                },
                "buffer_factors": {"low": 0.1, "normal": 0.15, "high": 0.2},
                "risk_offset_factors": {"low": 0.35, "normal": 0.45, "high": 0.6},
            },
            "validity_window_hours": {
                "base": 6,
                "low_vol_adjustment": 1,
                "normal_vol_adjustment": 0,
                "high_vol_adjustment": -1,
                "min": 4,
                "max": 8,
            },
        }
    )


class _ProviderStub:
    def __init__(self, candles):
        self.candles = candles

    def fetch_hourly_candles(self, pair: str, lookback: int = 120):
        _ = pair
        _ = lookback
        return self.candles


def _candles() -> list[HourlyCandle]:
    rows = []
    price = 149.0
    for idx in range(40):
        price += 0.03
        rows.append(
            HourlyCandle(
                timestamp=f"2026-03-01T{idx%24:02d}:00:00Z",
                open=price - 0.02,
                high=price + 0.06,
                low=price - 0.07,
                close=price,
            )
        )
    return rows


class SignalSetupTests(unittest.TestCase):
    def test_build_execution_plan_bullish(self):
        signal = SignalCandidate(
            signal_id="sig_1",
            pair="USD/JPY",
            direction="bullish",
            horizon="intraday",
            confidence_raw=0.75,
            confidence_calibrated=0.72,
            thesis="fixture",
            invalidation="fixture",
            reasons=["event=employment"],
            created_at="2026-03-01T12:00:00Z",
        )
        plan = build_execution_plan(
            signal=signal,
            strategy=_strategy_stub(),
            intraday_provider=_ProviderStub(_candles()),
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertGreater(plan.entry_trigger_price, plan.risk_line_price)
        self.assertIn("closes bullish above", plan.when_to_enter)
        self.assertGreaterEqual(plan.valid_for_hours, 4)
        self.assertLessEqual(plan.valid_for_hours, 8)

    def test_build_execution_plan_returns_none_when_data_insufficient(self):
        signal = SignalCandidate(
            signal_id="sig_2",
            pair="EUR/USD",
            direction="bearish",
            horizon="intraday",
            confidence_raw=0.75,
            confidence_calibrated=0.72,
            thesis="fixture",
            invalidation="fixture",
            reasons=["event=inflation"],
            created_at="2026-03-01T12:00:00Z",
        )
        plan = build_execution_plan(
            signal=signal,
            strategy=_strategy_stub(),
            intraday_provider=_ProviderStub(_candles()[:10]),
        )
        self.assertIsNone(plan)


if __name__ == "__main__":
    unittest.main()
