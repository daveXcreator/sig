import unittest
from unittest.mock import patch
import requests

from app.economic_calendar import (
    EconomicEvent,
    FmpEconomicCalendarClient,
    event_surprise_strength,
    pair_surprise_strength,
)


class EconomicCalendarTests(unittest.TestCase):
    def test_event_surprise_strength_prefers_actual_vs_estimate(self):
        event = EconomicEvent(
            date="2026-02-28",
            event="CPI",
            currency="USD",
            country="US",
            impact="high",
            actual="3.4",
            estimate="3.0",
            previous="2.9",
        )
        score = event_surprise_strength(event)
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_pair_surprise_strength_maps_by_currency(self):
        events = [
            EconomicEvent("2026-02-28", "CPI", "USD", "US", "high", "3.2", "3.0", "2.8"),
            EconomicEvent("2026-02-28", "GDP", "JPY", "Japan", "medium", "0.4", "0.2", "0.1"),
        ]
        surprise = pair_surprise_strength(events, ["EUR/USD", "USD/JPY", "GBP/USD"])
        self.assertIn("EUR/USD", surprise)
        self.assertIn("USD/JPY", surprise)
        self.assertGreaterEqual(surprise["USD/JPY"], surprise["EUR/USD"])

    @patch("app.economic_calendar.requests.get")
    def test_fmp_client_parses_payload(self, requests_get_mock):
        payload = [
            {
                "date": "2026-02-28 13:30:00",
                "country": "US",
                "event": "Nonfarm Payrolls",
                "currency": "USD",
                "impact": "High",
                "actual": "210K",
                "estimate": "180K",
                "previous": "175K",
            }
        ]
        response = requests_get_mock.return_value
        response.raise_for_status.return_value = None
        response.json.return_value = payload

        client = FmpEconomicCalendarClient(api_key="dummy")
        events = client.fetch_events("2026-02-27", "2026-03-01")
        self.assertEqual(1, len(events))
        self.assertEqual("USD", events[0].currency)
        self.assertEqual("high", events[0].impact)

    @patch("app.economic_calendar.time.sleep")
    @patch("app.economic_calendar.requests.get")
    def test_fmp_client_retries_and_fallbacks(self, requests_get_mock, _sleep_mock):
        first_error = requests.RequestException("network")
        good_response = type("Resp", (), {})()
        good_response.raise_for_status = lambda: None
        good_response.json = lambda: [
            {
                "date": "2026-02-28",
                "country": "Japan",
                "event": "CPI",
                "impact": "Medium",
                "actual": "2.0",
                "estimate": "1.8",
                "previous": "1.7",
            }
        ]
        requests_get_mock.side_effect = [first_error, good_response]

        client = FmpEconomicCalendarClient(api_key="dummy")
        events = client.fetch_events("2026-02-27", "2026-03-01")

        self.assertEqual(1, len(events))
        self.assertEqual("JPY", events[0].currency)


if __name__ == "__main__":
    unittest.main()
