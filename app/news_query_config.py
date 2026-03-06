from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from app.config import NEWS_QUERY_CONFIG_PATH


class NewsQueryConfigError(ValueError):
    pass


DEFAULT_QUERY_CONFIG: dict[str, Any] = {
    "newsapi_query_groups": [
        "forex OR currency OR fx market",
        "federal reserve OR ecb OR boe OR boj OR central bank",
        "inflation OR cpi OR ppi OR nonfarm payroll OR unemployment",
        "geopolitical OR sanctions OR conflict OR crude oil OR treasury yields",
    ],
    "google_rss_queries": [
        "forex currency central bank",
        "fed ecb boe boj rates inflation",
        "nonfarm payroll cpi forex dollar yen euro",
        "geopolitical sanctions war oil markets",
    ],
    "newsapi_page_size": 10,
    "newsapi_max_pages": 1,
    "google_items_per_query": 5,
}

REQUIRED_KEYS = {
    "newsapi_query_groups",
    "google_rss_queries",
    "newsapi_page_size",
    "newsapi_max_pages",
    "google_items_per_query",
}


def _require_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise NewsQueryConfigError(f"{field_name} must be a list")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise NewsQueryConfigError(f"{field_name} must contain strings only")
        cleaned = item.strip()
        if not cleaned:
            raise NewsQueryConfigError(f"{field_name} cannot contain empty strings")
        out.append(cleaned)
    if not out:
        raise NewsQueryConfigError(f"{field_name} cannot be empty")
    return out


def _require_int_range(value: Any, field_name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise NewsQueryConfigError(f"{field_name} must be an integer") from None
    if parsed < minimum or parsed > maximum:
        raise NewsQueryConfigError(
            f"{field_name} must be between {minimum} and {maximum}"
        )
    return parsed


def validate_news_query_config(payload: dict[str, Any]) -> None:
    missing = REQUIRED_KEYS - set(payload.keys())
    if missing:
        raise NewsQueryConfigError(
            f"Missing query config sections: {sorted(missing)}"
        )

    _require_string_list(payload["newsapi_query_groups"], "newsapi_query_groups")
    _require_string_list(payload["google_rss_queries"], "google_rss_queries")
    _require_int_range(payload["newsapi_page_size"], "newsapi_page_size", 1, 100)
    _require_int_range(payload["newsapi_max_pages"], "newsapi_max_pages", 1, 5)
    _require_int_range(payload["google_items_per_query"], "google_items_per_query", 1, 50)


@dataclass(slots=True)
class NewsQueryConfig:
    path: str
    raw: dict[str, Any]

    @property
    def newsapi_query_groups(self) -> list[str]:
        return _require_string_list(self.raw["newsapi_query_groups"], "newsapi_query_groups")

    @property
    def google_rss_queries(self) -> list[str]:
        return _require_string_list(self.raw["google_rss_queries"], "google_rss_queries")

    @property
    def newsapi_page_size(self) -> int:
        return _require_int_range(self.raw["newsapi_page_size"], "newsapi_page_size", 1, 100)

    @property
    def newsapi_max_pages(self) -> int:
        return _require_int_range(self.raw["newsapi_max_pages"], "newsapi_max_pages", 1, 5)

    @property
    def google_items_per_query(self) -> int:
        return _require_int_range(
            self.raw["google_items_per_query"], "google_items_per_query", 1, 50
        )


def load_news_query_config(path: str | None = None) -> NewsQueryConfig:
    config_path = Path(path or NEWS_QUERY_CONFIG_PATH)
    if not config_path.exists():
        raise NewsQueryConfigError(f"News query config file not found: {config_path}")

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise NewsQueryConfigError(
            f"Invalid JSON in news query config: {config_path}"
        ) from err

    if not isinstance(payload, dict):
        raise NewsQueryConfigError("News query config root must be an object")

    validate_news_query_config(payload)
    return NewsQueryConfig(path=str(config_path), raw=payload)
