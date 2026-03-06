from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time

import requests

from app.config import ALPHA_VANTAGE_KEY, RSI_PERIOD
from app.schemas import MarketContext
from app.utils import log

BASE_URL = "https://www.alphavantage.co/query"
ATR_PERIOD = 14
TREND_WINDOW = 20
DEFAULT_LOOKBACK = 120
MAX_API_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.2
MIN_REQUEST_INTERVAL_SECONDS = 12.5
CACHE_TTL_SECONDS = 60 * 60 * 6
MAX_CACHE_STALE_SECONDS = 60 * 60 * 24 * 3
CACHE_DIR = Path("artifacts/cache/alpha_vantage")


def parse_pair(pair: str) -> tuple[str, str]:
    if "/" not in pair:
        raise ValueError(f"Invalid pair format: {pair}")
    base, quote = pair.split("/", 1)
    if len(base) != 3 or len(quote) != 3:
        raise ValueError(f"Invalid pair format: {pair}")
    return base, quote


@dataclass(slots=True)
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float


def compute_rsi(closes: list[float], period: int = RSI_PERIOD) -> float:
    if len(closes) <= period:
        return 50.0

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return max(0.0, min(100.0, rsi))


def compute_trend_score(closes: list[float], window: int = TREND_WINDOW) -> float:
    if len(closes) < 2:
        return 0.5

    sample = closes[-window:] if len(closes) >= window else closes
    start = sample[0]
    end = sample[-1]
    if start == 0:
        return 0.5

    pct_move = (end - start) / start
    bounded = max(-1.0, min(1.0, pct_move * 12.0))
    score = 0.5 + (bounded / 2.0)
    return max(0.0, min(1.0, score))


def compute_true_ranges(candles: list[Candle]) -> list[float]:
    if not candles:
        return []

    true_ranges: list[float] = []
    prev_close = candles[0].close
    for candle in candles:
        tr = max(
            candle.high - candle.low,
            abs(candle.high - prev_close),
            abs(candle.low - prev_close),
        )
        true_ranges.append(max(0.0, tr))
        prev_close = candle.close

    return true_ranges


def compute_atr_series(true_ranges: list[float], period: int = ATR_PERIOD) -> list[float]:
    if len(true_ranges) < period:
        return []

    atr_values: list[float] = []
    current_atr = sum(true_ranges[:period]) / period
    atr_values.append(current_atr)

    for tr in true_ranges[period:]:
        current_atr = ((current_atr * (period - 1)) + tr) / period
        atr_values.append(current_atr)

    return atr_values


def percentile_of_last(values: list[float]) -> float:
    if not values:
        return 0.5
    last = values[-1]
    less_or_equal = sum(1 for value in values if value <= last)
    return less_or_equal / len(values)


def classify_volatility_regime(atr_percentile: float) -> str:
    if atr_percentile < 0.33:
        return "low"
    if atr_percentile > 0.66:
        return "high"
    return "normal"


def compute_technical_alignment_score(
    rsi: float,
    trend_score: float,
    atr_percentile: float,
) -> float:
    trend_strength = abs(trend_score - 0.5) * 2.0
    momentum_strength = abs(rsi - 50.0) / 50.0
    volatility_quality = 1.0 - min(1.0, abs(atr_percentile - 0.5) * 2.0)

    score = (
        0.45 * trend_strength
        + 0.35 * momentum_strength
        + 0.20 * volatility_quality
    )
    return max(0.0, min(1.0, score))


def build_market_context(pair: str, candles: list[Candle]) -> MarketContext:
    if not candles:
        raise ValueError("candles cannot be empty")

    closes = [candle.close for candle in candles]
    rsi = compute_rsi(closes)
    trend_score = compute_trend_score(closes)

    true_ranges = compute_true_ranges(candles)
    atr_series = compute_atr_series(true_ranges)
    atr_percentile = percentile_of_last(atr_series[-100:] if len(atr_series) > 100 else atr_series)
    volatility_regime = classify_volatility_regime(atr_percentile)
    technical_alignment_score = compute_technical_alignment_score(
        rsi=rsi,
        trend_score=trend_score,
        atr_percentile=atr_percentile,
    )

    return MarketContext(
        pair=pair,
        timestamp=candles[-1].timestamp,
        rsi=rsi,
        trend_score=trend_score,
        volatility_regime=volatility_regime,
        atr_percentile=atr_percentile,
        technical_alignment_score=technical_alignment_score,
    )


class AlphaVantageMarketContextProvider:
    def __init__(
        self,
        api_key: str | None = ALPHA_VANTAGE_KEY,
        use_cache: bool = True,
        cache_ttl_seconds: int = CACHE_TTL_SECONDS,
        min_request_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
        cache_dir: Path = CACHE_DIR,
    ):
        self.api_key = api_key
        self.use_cache = use_cache
        self.cache_ttl_seconds = cache_ttl_seconds
        self.min_request_interval_seconds = max(0.0, float(min_request_interval_seconds))
        self.cache_dir = cache_dir
        self._last_request_epoch = 0.0
        self._rate_limited_recently = False
        self._rate_limit_log_emitted = False

    def _cache_path(self, pair: str) -> Path:
        return self.cache_dir / f"{pair.replace('/', '_')}.json"

    def _load_cached_candles(
        self,
        pair: str,
        max_age_seconds: int,
        lookback: int,
    ) -> list[Candle]:
        if not self.use_cache:
            return []
        path = self._cache_path(pair)
        if not path.exists():
            return []

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

        fetched_at = float(payload.get("fetched_at_epoch", 0.0))
        if fetched_at <= 0:
            return []
        age = max(0.0, time.time() - fetched_at)
        if age > max_age_seconds:
            return []

        cached_rows = payload.get("candles", [])
        candles: list[Candle] = []
        for row in cached_rows if isinstance(cached_rows, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                candles.append(
                    Candle(
                        timestamp=str(row["timestamp"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

        if not candles:
            return []
        return candles[-lookback:] if len(candles) > lookback else candles

    def _save_cached_candles(self, pair: str, candles: list[Candle]) -> None:
        if not self.use_cache or not candles:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "fetched_at_epoch": time.time(),
                "candles": [
                    {
                        "timestamp": candle.timestamp,
                        "open": candle.open,
                        "high": candle.high,
                        "low": candle.low,
                        "close": candle.close,
                    }
                    for candle in candles
                ],
            }
            self._cache_path(pair).write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            # Cache should never break the pipeline.
            return

    def _respect_rate_limit_window(self) -> None:
        if self.min_request_interval_seconds <= 0:
            return
        elapsed = time.time() - self._last_request_epoch
        if elapsed >= self.min_request_interval_seconds:
            return
        time.sleep(self.min_request_interval_seconds - elapsed)

    def fetch_daily_candles(self, pair: str, lookback: int = DEFAULT_LOOKBACK) -> list[Candle]:
        if not self.api_key:
            log("ALPHA_VANTAGE_KEY is missing; skipping market context fetch.")
            return []

        fresh_cached = self._load_cached_candles(
            pair=pair,
            max_age_seconds=self.cache_ttl_seconds,
            lookback=lookback,
        )
        if fresh_cached:
            return fresh_cached

        if self._rate_limited_recently:
            stale_cached = self._load_cached_candles(
                pair=pair,
                max_age_seconds=MAX_CACHE_STALE_SECONDS,
                lookback=lookback,
            )
            if stale_cached:
                return stale_cached
            return []

        base, quote = parse_pair(pair)
        params = {
            "function": "FX_DAILY",
            "from_symbol": base,
            "to_symbol": quote,
            "outputsize": "compact",
            "apikey": self.api_key,
        }

        data = None
        for attempt in range(1, MAX_API_RETRIES + 1):
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
                if attempt == MAX_API_RETRIES:
                    log(f"Market context request failed for {pair} after retries.")
                    return []
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            except Exception:
                log(f"Market context unexpected failure for {pair}.")
                return []

        if data is None:
            return []

        if "Note" in data or "Information" in data:
            self._rate_limited_recently = True
            if not self._rate_limit_log_emitted:
                log("Alpha Vantage rate limit/plan response. Falling back to cache where available.")
                self._rate_limit_log_emitted = True
            stale_cached = self._load_cached_candles(
                pair=pair,
                max_age_seconds=MAX_CACHE_STALE_SECONDS,
                lookback=lookback,
            )
            return stale_cached
        if "Error Message" in data:
            log(f"Alpha Vantage error response for {pair}.")
            stale_cached = self._load_cached_candles(
                pair=pair,
                max_age_seconds=MAX_CACHE_STALE_SECONDS,
                lookback=lookback,
            )
            return stale_cached

        series = data.get("Time Series FX (Daily)", {})
        if not series:
            log(f"No FX_DAILY data for {pair}.")
            stale_cached = self._load_cached_candles(
                pair=pair,
                max_age_seconds=MAX_CACHE_STALE_SECONDS,
                lookback=lookback,
            )
            return stale_cached

        candles: list[Candle] = []
        for timestamp in sorted(series.keys()):
            entry = series[timestamp]
            try:
                candles.append(
                    Candle(
                        timestamp=f"{timestamp}T00:00:00Z",
                        open=float(entry["1. open"]),
                        high=float(entry["2. high"]),
                        low=float(entry["3. low"]),
                        close=float(entry["4. close"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

        if len(candles) > lookback:
            candles = candles[-lookback:]
        self._save_cached_candles(pair=pair, candles=candles)
        return candles

    def build_context(self, pairs: list[str]) -> list[MarketContext]:
        contexts: list[MarketContext] = []
        for pair in pairs:
            candles = self.fetch_daily_candles(pair)
            if not candles:
                continue
            try:
                contexts.append(build_market_context(pair=pair, candles=candles))
            except Exception:
                log(f"Failed to build market context for {pair}.")
        return contexts
