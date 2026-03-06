from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re
import time

import requests

from app.config import FMP_API_KEY
from app.utils import log

FMP_BASE_URLS = (
    "https://financialmodelingprep.com/api/v3/economic_calendar",
    "https://financialmodelingprep.com/stable/economic-calendar",
)
MAX_API_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.2
IMPACT_TO_WEIGHT = {
    "high": 1.0,
    "medium": 0.6,
    "low": 0.3,
}
COUNTRY_TO_CURRENCY = {
    "US": "USD",
    "USA": "USD",
    "UNITED STATES": "USD",
    "EU": "EUR",
    "EURO AREA": "EUR",
    "EUROZONE": "EUR",
    "JP": "JPY",
    "JAPAN": "JPY",
    "UK": "GBP",
    "UNITED KINGDOM": "GBP",
    "GB": "GBP",
    "SWITZERLAND": "CHF",
    "CH": "CHF",
    "AUSTRALIA": "AUD",
    "AU": "AUD",
    "CANADA": "CAD",
    "CA": "CAD",
    "NEW ZEALAND": "NZD",
    "NZ": "NZD",
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _safe_float(value: str | int | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "")
    unit = 1.0
    if text.endswith("%"):
        text = text[:-1]
    if text.endswith("K"):
        text = text[:-1]
        unit = 1_000.0
    elif text.endswith("M"):
        text = text[:-1]
        unit = 1_000_000.0
    elif text.endswith("B"):
        text = text[:-1]
        unit = 1_000_000_000.0
    text = re.sub(r"[^0-9.\-]", "", text)
    if not text:
        return None
    try:
        return float(text) * unit
    except ValueError:
        return None


@dataclass(slots=True)
class EconomicEvent:
    date: str
    event: str
    currency: str
    country: str
    impact: str
    actual: str | None
    estimate: str | None
    previous: str | None


class FmpEconomicCalendarClient:
    def __init__(self, api_key: str | None = FMP_API_KEY):
        self.api_key = api_key

    def fetch_events(
        self,
        from_date: str,
        to_date: str,
    ) -> list[EconomicEvent]:
        if not self.api_key:
            log("FMP_API_KEY is missing; skipping economic calendar fetch.")
            return []

        payload = None
        auth_failed = False
        rate_limited = False
        http_failed = False
        request_failed = False

        def _looks_like_auth_error(value: object) -> bool:
            if not isinstance(value, dict):
                return False
            text = " ".join(str(item) for item in value.values()).lower()
            return ("api key" in text or "apikey" in text) and (
                "invalid" in text or "missing" in text or "claim your free api key" in text
            )

        def _looks_like_rate_limit(value: object) -> bool:
            if not isinstance(value, dict):
                return False
            text = " ".join(str(item) for item in value.values()).lower()
            return "rate limit" in text or "too many requests" in text

        for base_url in FMP_BASE_URLS:
            params = {
                "from": from_date,
                "to": to_date,
                "apikey": self.api_key,
            }
            for attempt in range(1, MAX_API_RETRIES + 1):
                try:
                    response = requests.get(
                        base_url,
                        params=params,
                        timeout=15,
                        headers={"User-Agent": "signalyze-ai/1.0"},
                    )
                    response.raise_for_status()
                    candidate_payload = response.json()
                    if _looks_like_auth_error(candidate_payload):
                        auth_failed = True
                        break
                    if _looks_like_rate_limit(candidate_payload):
                        rate_limited = True
                        if attempt < MAX_API_RETRIES:
                            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                            continue
                        break
                    payload = candidate_payload
                    break
                except requests.HTTPError as err:
                    status = err.response.status_code if err.response is not None else 0
                    if status in {401, 403}:
                        auth_failed = True
                        break
                    if status == 429:
                        rate_limited = True
                        if attempt < MAX_API_RETRIES:
                            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                            continue
                        break
                    http_failed = True
                    if attempt < MAX_API_RETRIES:
                        time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                        continue
                except requests.RequestException:
                    request_failed = True
                    if attempt < MAX_API_RETRIES:
                        time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                        continue
                except Exception:
                    log("Economic calendar request unexpected failure.")
                    return []
            if auth_failed:
                break
            if payload is not None:
                break

        if payload is None:
            if auth_failed:
                log("Economic calendar auth failed. Check FMP_API_KEY.")
            elif rate_limited:
                log("Economic calendar rate limited.")
            elif http_failed:
                log("Economic calendar HTTP failure.")
            elif request_failed:
                log("Economic calendar request failed.")
            return []

        events: list[EconomicEvent] = []
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            currency = str(item.get("currency") or "").upper().strip()
            country = str(item.get("country") or "").strip()
            if not currency and country:
                currency = COUNTRY_TO_CURRENCY.get(country.upper(), "")
            if not currency:
                continue
            events.append(
                EconomicEvent(
                    date=str(item.get("date") or ""),
                    event=str(item.get("event") or "").strip(),
                    currency=currency,
                    country=country,
                    impact=str(item.get("impact") or "medium").lower().strip(),
                    actual=item.get("actual"),
                    estimate=item.get("estimate") or item.get("consensus") or item.get("forecast"),
                    previous=item.get("previous"),
                )
            )
        return events

    def fetch_recent_window(self, days_back: int = 1, days_forward: int = 1) -> list[EconomicEvent]:
        today = date.today()
        from_date = (today - timedelta(days=days_back)).isoformat()
        to_date = (today + timedelta(days=days_forward)).isoformat()
        return self.fetch_events(from_date=from_date, to_date=to_date)


def event_surprise_strength(event: EconomicEvent) -> float:
    actual = _safe_float(event.actual)
    estimate = _safe_float(event.estimate)
    previous = _safe_float(event.previous)

    impact_weight = IMPACT_TO_WEIGHT.get(event.impact, 0.5)

    if actual is not None and estimate is not None:
        baseline = max(1e-9, abs(estimate))
        magnitude = abs(actual - estimate) / baseline
        return _clamp01(min(1.0, magnitude) * (0.5 + 0.5 * impact_weight))

    if actual is not None and previous is not None:
        baseline = max(1e-9, abs(previous))
        magnitude = abs(actual - previous) / baseline
        return _clamp01(min(1.0, magnitude) * (0.35 + 0.5 * impact_weight))

    return _clamp01(0.2 * impact_weight)


def pair_surprise_strength(events: list[EconomicEvent], pairs: list[str]) -> dict[str, float]:
    surprises: dict[str, float] = {pair: 0.0 for pair in pairs}
    for pair in pairs:
        if "/" not in pair:
            continue
        base, quote = pair.split("/", 1)
        pair_events = [
            event for event in events if event.currency in {base, quote}
        ]
        if not pair_events:
            continue
        surprises[pair] = max(event_surprise_strength(event) for event in pair_events)
    return surprises
