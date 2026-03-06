from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import time

import requests

from app.config import ALPHA_VANTAGE_KEY
from app.schemas import SignalCandidate
from app.strategy_config import MajorEventStrategyConfig
from app.utils import log

BASE_URL = "https://www.alphavantage.co/query"
MAX_RETRIES = 2
MIN_REQUEST_INTERVAL_SECONDS = 12.5


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
class HourlyCandle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float


@dataclass(slots=True)
class SignalExecutionPlan:
    signal_id: str
    pair: str
    direction: str
    entry_trigger_price: float
    risk_line_price: float
    valid_for_hours: int
    valid_until: str
    when_to_enter: str
    risk_line_text: str
    volatility_bucket: str


def _parse_pair(pair: str) -> tuple[str, str]:
    if "/" not in pair:
        raise ValueError(f"invalid pair {pair}")
    base, quote = pair.split("/", 1)
    return base, quote


def _compute_true_ranges(candles: list[HourlyCandle]) -> list[float]:
    if len(candles) < 2:
        return []
    values: list[float] = []
    prev_close = candles[0].close
    for candle in candles[1:]:
        tr = max(
            candle.high - candle.low,
            abs(candle.high - prev_close),
            abs(candle.low - prev_close),
        )
        values.append(max(0.0, tr))
        prev_close = candle.close
    return values


def _atr_series(true_ranges: list[float], period: int) -> list[float]:
    if len(true_ranges) < period or period <= 0:
        return []
    current = sum(true_ranges[:period]) / period
    values = [current]
    for tr in true_ranges[period:]:
        current = ((current * (period - 1)) + tr) / period
        values.append(current)
    return values


def _percentile_of_last(values: list[float]) -> float:
    if not values:
        return 0.5
    last = values[-1]
    le_count = sum(1 for item in values if item <= last)
    return le_count / len(values)


def _volatility_bucket(atr_percentile: float, strategy: MajorEventStrategyConfig) -> str:
    conf = strategy.raw["volatility_buckets"]
    if atr_percentile < float(conf["low_max_atr_percentile"]):
        return "low"
    if atr_percentile <= float(conf["normal_max_atr_percentile"]):
        return "normal"
    return "high"


class AlphaVantageIntradayProvider:
    def __init__(
        self,
        api_key: str | None = ALPHA_VANTAGE_KEY,
        min_request_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
    ):
        self.api_key = api_key
        self.min_request_interval_seconds = max(0.0, float(min_request_interval_seconds))
        self._last_request_epoch = 0.0

    def _respect_rate_limit_window(self) -> None:
        if self.min_request_interval_seconds <= 0:
            return
        elapsed = time.time() - self._last_request_epoch
        if elapsed >= self.min_request_interval_seconds:
            return
        time.sleep(self.min_request_interval_seconds - elapsed)

    def fetch_hourly_candles(self, pair: str, lookback: int = 120) -> list[HourlyCandle]:
        if not self.api_key:
            return []
        base, quote = _parse_pair(pair)
        params = {
            "function": "FX_INTRADAY",
            "from_symbol": base,
            "to_symbol": quote,
            "interval": "60min",
            "outputsize": "compact",
            "apikey": self.api_key,
        }

        data = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._respect_rate_limit_window()
                response = requests.get(
                    BASE_URL,
                    params=params,
                    timeout=15,
                    headers={"User-Agent": "signalyze-ai/1.0"},
                )
                self._last_request_epoch = time.time()
                response.raise_for_status()
                data = response.json()
                break
            except requests.RequestException:
                self._last_request_epoch = time.time()
                if attempt == MAX_RETRIES:
                    return []
                time.sleep(1.2 * attempt)
            except Exception:
                return []

        if not isinstance(data, dict):
            return []
        if "Note" in data or "Information" in data or "Error Message" in data:
            return []

        series = data.get("Time Series FX (60min)", {})
        if not isinstance(series, dict) or not series:
            return []

        candles: list[HourlyCandle] = []
        for timestamp in sorted(series.keys()):
            row = series.get(timestamp)
            if not isinstance(row, dict):
                continue
            try:
                candles.append(
                    HourlyCandle(
                        timestamp=f"{timestamp.replace(' ', 'T')}Z",
                        open=float(row["1. open"]),
                        high=float(row["2. high"]),
                        low=float(row["3. low"]),
                        close=float(row["4. close"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        if len(candles) > lookback:
            candles = candles[-lookback:]
        return candles

    def get_latest_close(self, pair: str) -> float | None:
        candles = self.fetch_hourly_candles(pair=pair, lookback=5)
        if not candles:
            return None
        return candles[-1].close


def build_execution_plan(
    signal: SignalCandidate,
    strategy: MajorEventStrategyConfig,
    intraday_provider: AlphaVantageIntradayProvider,
) -> SignalExecutionPlan | None:
    entry_conf = strategy.raw["entry_and_risk"]
    lookback = int(entry_conf["lookback_bars_1h"])
    atr_period = int(entry_conf["atr_period_1h"])

    candles = intraday_provider.fetch_hourly_candles(signal.pair, lookback=max(80, lookback + atr_period + 5))
    if len(candles) < lookback + atr_period + 2:
        return None

    history = candles[:-1] if len(candles) > 1 else candles
    if len(history) < lookback:
        return None
    structure = history[-lookback:]
    swing_high = max(candle.high for candle in structure)
    swing_low = min(candle.low for candle in structure)

    true_ranges = _compute_true_ranges(history)
    atr_values = _atr_series(true_ranges, period=atr_period)
    if not atr_values:
        return None
    atr = atr_values[-1]
    if not math.isfinite(atr) or atr <= 0:
        return None
    atr_percentile = _percentile_of_last(atr_values[-60:] if len(atr_values) > 60 else atr_values)
    bucket = _volatility_bucket(atr_percentile=atr_percentile, strategy=strategy)

    multipliers = entry_conf["pair_multipliers"]
    pair_multiplier = float(multipliers.get(signal.pair, 1.1))
    buffer_factor = float(entry_conf["buffer_factors"][bucket])
    risk_factor = float(entry_conf["risk_offset_factors"][bucket])

    buffer = atr * buffer_factor * pair_multiplier
    risk_offset = atr * risk_factor * pair_multiplier

    if signal.direction == "bullish":
        entry_price = swing_high + buffer
        risk_line = swing_low - risk_offset
        if risk_line >= entry_price:
            risk_line = entry_price - max(atr * 0.35, 0.0001)
        when_to_enter = (
            f"Enter only after a 1h candle closes bullish above {entry_price:.5f}."
        )
        risk_line_text = (
            f"Exit if a 1h candle closes back below {risk_line:.5f}."
        )
    else:
        entry_price = swing_low - buffer
        risk_line = swing_high + risk_offset
        if risk_line <= entry_price:
            risk_line = entry_price + max(atr * 0.35, 0.0001)
        when_to_enter = (
            f"Enter only after a 1h candle closes bearish below {entry_price:.5f}."
        )
        risk_line_text = (
            f"Exit if a 1h candle closes back above {risk_line:.5f}."
        )

    validity = strategy.raw["validity_window_hours"]
    base_hours = int(validity["base"])
    adjust_key = {
        "low": "low_vol_adjustment",
        "normal": "normal_vol_adjustment",
        "high": "high_vol_adjustment",
    }[bucket]
    adjusted = base_hours + int(validity[adjust_key])
    valid_for_hours = max(int(validity["min"]), min(int(validity["max"]), adjusted))

    created_at = _parse_iso8601_utc(signal.created_at) or datetime.now(timezone.utc)
    valid_until = created_at + timedelta(hours=valid_for_hours)

    return SignalExecutionPlan(
        signal_id=signal.signal_id,
        pair=signal.pair,
        direction=signal.direction,
        entry_trigger_price=entry_price,
        risk_line_price=risk_line,
        valid_for_hours=valid_for_hours,
        valid_until=valid_until.isoformat().replace("+00:00", "Z"),
        when_to_enter=when_to_enter,
        risk_line_text=risk_line_text,
        volatility_bucket=bucket,
    )


def build_execution_plans(
    signals: list[SignalCandidate],
    strategy: MajorEventStrategyConfig,
    intraday_provider: AlphaVantageIntradayProvider,
) -> dict[str, SignalExecutionPlan]:
    plans: dict[str, SignalExecutionPlan] = {}
    for signal in signals:
        plan = build_execution_plan(
            signal=signal,
            strategy=strategy,
            intraday_provider=intraday_provider,
        )
        if plan is None:
            log(f"Could not build execution plan for {signal.signal_id} ({signal.pair}).")
            continue
        plans[signal.signal_id] = plan
    return plans
