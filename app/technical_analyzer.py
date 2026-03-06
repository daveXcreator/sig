import requests

from app.config import (
    ALPHA_VANTAGE_KEY,
    RSI_PERIOD,
    RSI_THRESHOLD_OVERBOUGHT,
    RSI_THRESHOLD_OVERSOLD,
)
from app.utils import log

BASE_URL = "https://www.alphavantage.co/query"


def parse_pair(pair: str) -> tuple[str, str]:
    if "/" not in pair:
        raise ValueError(f"Invalid pair format: {pair}")

    from_symbol, to_symbol = pair.split("/", 1)
    if len(from_symbol) != 3 or len(to_symbol) != 3:
        raise ValueError(f"Invalid pair format: {pair}")

    return from_symbol, to_symbol


def get_rsi(pair: str, interval: str = "daily", time_period: int = RSI_PERIOD) -> dict | None:
    if not ALPHA_VANTAGE_KEY:
        log("ALPHA_VANTAGE_KEY is missing; skipping RSI lookup.")
        return None

    from_symbol, to_symbol = parse_pair(pair)

    params = {
        "function": "RSI",
        "symbol": f"{from_symbol}{to_symbol}",
        "interval": interval,
        "time_period": time_period,
        "series_type": "close",
        "apikey": ALPHA_VANTAGE_KEY,
    }

    try:
        response = requests.get(BASE_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        if "Note" in data:
            log(f"Alpha Vantage rate limit response for {pair}: {data['Note']}")
            return None

        rsi_series = data.get("Technical Analysis: RSI", {})
        if not rsi_series:
            log(f"No RSI data for {pair}")
            return None

        latest_date = sorted(rsi_series.keys())[-1]
        latest_rsi = float(rsi_series[latest_date]["RSI"])

        if latest_rsi < RSI_THRESHOLD_OVERSOLD:
            signal = "bullish"
        elif latest_rsi > RSI_THRESHOLD_OVERBOUGHT:
            signal = "bearish"
        else:
            signal = "neutral"

        log(f"{pair} RSI: {latest_rsi:.2f} -> {signal}")
        return {"pair": pair, "rsi": latest_rsi, "signal": signal}

    except requests.RequestException:
        log(f"RSI fetch error for {pair}: request failed.")
        return None
    except Exception:
        log(f"RSI fetch error for {pair}: unexpected failure.")
        return None


def analyze_technical(pairs: list[str]) -> list[dict]:
    results = []
    for pair in pairs:
        result = get_rsi(pair)
        if result:
            results.append(result)
    return results
