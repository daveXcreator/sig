import unittest
from unittest.mock import patch

from app.market_context import (
    AlphaVantageMarketContextProvider,
    Candle,
    build_market_context,
    classify_volatility_regime,
    compute_rsi,
    compute_trend_score,
)


def _synthetic_candles(
    days: int = 80,
    start: float = 1.10,
    drift: float = 0.001,
    volatility: float = 0.002,
) -> list[Candle]:
    candles: list[Candle] = []
    close = start
    for day in range(days):
        wave = ((day % 5) - 2) * volatility * 0.4
        close = max(0.0001, close * (1.0 + drift + wave))
        high = close * (1.0 + volatility)
        low = close * (1.0 - volatility)
        open_price = close * (1.0 - drift * 0.5)
        candles.append(
            Candle(
                timestamp=f"2026-01-{(day % 28) + 1:02d}T00:00:00Z",
                open=open_price,
                high=high,
                low=low,
                close=close,
            )
        )
    return candles


class MarketContextFeatureTests(unittest.TestCase):
    def test_compute_rsi_range_and_bias(self):
        uptrend = [1 + i * 0.01 for i in range(40)]
        downtrend = [2 - i * 0.01 for i in range(40)]

        up_rsi = compute_rsi(uptrend)
        down_rsi = compute_rsi(downtrend)

        self.assertGreaterEqual(up_rsi, 0.0)
        self.assertLessEqual(up_rsi, 100.0)
        self.assertGreaterEqual(down_rsi, 0.0)
        self.assertLessEqual(down_rsi, 100.0)
        self.assertGreater(up_rsi, down_rsi)

    def test_compute_trend_score_directionality(self):
        uptrend = [1 + i * 0.01 for i in range(30)]
        downtrend = [2 - i * 0.01 for i in range(30)]

        up_score = compute_trend_score(uptrend)
        down_score = compute_trend_score(downtrend)

        self.assertGreaterEqual(up_score, 0.0)
        self.assertLessEqual(up_score, 1.0)
        self.assertGreaterEqual(down_score, 0.0)
        self.assertLessEqual(down_score, 1.0)
        self.assertGreater(up_score, down_score)

    def test_volatility_regime_thresholds(self):
        self.assertEqual("low", classify_volatility_regime(0.2))
        self.assertEqual("normal", classify_volatility_regime(0.5))
        self.assertEqual("high", classify_volatility_regime(0.9))

    def test_build_market_context_includes_expanded_features(self):
        candles = _synthetic_candles(days=90, drift=0.0008, volatility=0.003)
        context = build_market_context(pair="EUR/USD", candles=candles)

        self.assertEqual("EUR/USD", context.pair)
        self.assertGreaterEqual(context.rsi, 0.0)
        self.assertLessEqual(context.rsi, 100.0)
        self.assertGreaterEqual(context.trend_score, 0.0)
        self.assertLessEqual(context.trend_score, 1.0)
        self.assertIn(context.volatility_regime, {"low", "normal", "high"})
        self.assertGreaterEqual(context.atr_percentile, 0.0)
        self.assertLessEqual(context.atr_percentile, 1.0)
        self.assertGreaterEqual(context.technical_alignment_score, 0.0)
        self.assertLessEqual(context.technical_alignment_score, 1.0)


class MarketContextProviderTests(unittest.TestCase):
    @patch("app.market_context.requests.get")
    def test_provider_build_context_with_mocked_market_data(self, requests_get_mock):
        payload = {
            "Time Series FX (Daily)": {
                "2026-02-01": {
                    "1. open": "1.1000",
                    "2. high": "1.1025",
                    "3. low": "1.0980",
                    "4. close": "1.1015",
                },
                "2026-02-02": {
                    "1. open": "1.1015",
                    "2. high": "1.1040",
                    "3. low": "1.1000",
                    "4. close": "1.1030",
                },
                "2026-02-03": {
                    "1. open": "1.1030",
                    "2. high": "1.1060",
                    "3. low": "1.1020",
                    "4. close": "1.1055",
                },
                "2026-02-04": {
                    "1. open": "1.1055",
                    "2. high": "1.1090",
                    "3. low": "1.1040",
                    "4. close": "1.1080",
                },
                "2026-02-05": {
                    "1. open": "1.1080",
                    "2. high": "1.1100",
                    "3. low": "1.1060",
                    "4. close": "1.1095",
                },
                "2026-02-06": {
                    "1. open": "1.1095",
                    "2. high": "1.1120",
                    "3. low": "1.1080",
                    "4. close": "1.1110",
                },
                "2026-02-07": {
                    "1. open": "1.1110",
                    "2. high": "1.1130",
                    "3. low": "1.1090",
                    "4. close": "1.1120",
                },
                "2026-02-08": {
                    "1. open": "1.1120",
                    "2. high": "1.1140",
                    "3. low": "1.1105",
                    "4. close": "1.1130",
                },
                "2026-02-09": {
                    "1. open": "1.1130",
                    "2. high": "1.1150",
                    "3. low": "1.1110",
                    "4. close": "1.1145",
                },
                "2026-02-10": {
                    "1. open": "1.1145",
                    "2. high": "1.1170",
                    "3. low": "1.1130",
                    "4. close": "1.1160",
                },
                "2026-02-11": {
                    "1. open": "1.1160",
                    "2. high": "1.1180",
                    "3. low": "1.1140",
                    "4. close": "1.1170",
                },
                "2026-02-12": {
                    "1. open": "1.1170",
                    "2. high": "1.1200",
                    "3. low": "1.1160",
                    "4. close": "1.1190",
                },
                "2026-02-13": {
                    "1. open": "1.1190",
                    "2. high": "1.1210",
                    "3. low": "1.1170",
                    "4. close": "1.1200",
                },
                "2026-02-14": {
                    "1. open": "1.1200",
                    "2. high": "1.1230",
                    "3. low": "1.1190",
                    "4. close": "1.1220",
                },
                "2026-02-15": {
                    "1. open": "1.1220",
                    "2. high": "1.1240",
                    "3. low": "1.1200",
                    "4. close": "1.1230",
                },
                "2026-02-16": {
                    "1. open": "1.1230",
                    "2. high": "1.1260",
                    "3. low": "1.1220",
                    "4. close": "1.1250",
                },
            }
        }

        response = requests_get_mock.return_value
        response.raise_for_status.return_value = None
        response.json.return_value = payload

        provider = AlphaVantageMarketContextProvider(api_key="dummy", use_cache=False)
        contexts = provider.build_context(["EUR/USD"])

        self.assertEqual(1, len(contexts))
        context = contexts[0]
        self.assertEqual("EUR/USD", context.pair)
        self.assertIn(context.volatility_regime, {"low", "normal", "high"})
        self.assertGreaterEqual(context.technical_alignment_score, 0.0)
        self.assertLessEqual(context.technical_alignment_score, 1.0)

    @patch("app.market_context.requests.get")
    def test_provider_handles_rate_limit_information_response(self, requests_get_mock):
        response = requests_get_mock.return_value
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "Information": "Thank you for using Alpha Vantage! Please visit ...",
        }

        provider = AlphaVantageMarketContextProvider(api_key="dummy", use_cache=False)
        contexts = provider.build_context(["USD/JPY"])

        self.assertEqual([], contexts)


if __name__ == "__main__":
    unittest.main()
