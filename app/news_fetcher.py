from __future__ import annotations

from collections import Counter
import re
from urllib.parse import quote_plus, urlparse

import feedparser
import requests

from app.config import NEWS_API_KEY
from app.news_query_config import (
    DEFAULT_QUERY_CONFIG,
    NewsQueryConfigError,
    load_news_query_config,
)
from app.utils import log

NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"
GOOGLE_RSS_TEMPLATE = (
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
)

NEWSAPI_QUERY_GROUPS: tuple[str, ...] = tuple(DEFAULT_QUERY_CONFIG["newsapi_query_groups"])
GOOGLE_RSS_QUERIES: tuple[str, ...] = tuple(DEFAULT_QUERY_CONFIG["google_rss_queries"])
NEWSAPI_PAGE_SIZE = int(DEFAULT_QUERY_CONFIG["newsapi_page_size"])
NEWSAPI_MAX_PAGES = int(DEFAULT_QUERY_CONFIG["newsapi_max_pages"])
GOOGLE_ITEMS_PER_QUERY = int(DEFAULT_QUERY_CONFIG["google_items_per_query"])


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_title(title: str) -> str:
    cleaned = _clean_text(title).lower()
    cleaned = re.sub(r"\s*[-|]\s*(reuters|bloomberg|forex\.com|investing\.com)$", "", cleaned)
    return cleaned.strip()


def _canonical_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path or ""
    return f"{parsed.netloc.lower()}{path.rstrip('/')}"


def _article_fingerprint(article: dict) -> str:
    title = _normalize_title(article.get("title", ""))
    canonical = _canonical_url(article.get("url", ""))
    if canonical:
        return f"{title}|{canonical}"
    summary = _clean_text(article.get("description", "")).lower()[:180]
    return f"{title}|{summary}"


def _dedupe_articles(candidates: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for article in candidates:
        title = _clean_text(article.get("title", ""))
        if not title:
            continue
        normalized = dict(article)
        normalized["title"] = title
        normalized["description"] = _clean_text(article.get("description", ""))
        normalized["url"] = str(article.get("url", "")).strip()
        normalized["published_at"] = str(article.get("published_at", "")).strip()

        fingerprint = _article_fingerprint(normalized)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(normalized)
    return deduped


def _resolve_query_config() -> dict[str, object]:
    try:
        loaded = load_news_query_config()
        return {
            "newsapi_query_groups": loaded.newsapi_query_groups,
            "google_rss_queries": loaded.google_rss_queries,
            "newsapi_page_size": loaded.newsapi_page_size,
            "newsapi_max_pages": loaded.newsapi_max_pages,
            "google_items_per_query": loaded.google_items_per_query,
            "path": loaded.path,
            "fallback": False,
        }
    except NewsQueryConfigError as err:
        log(f"News query config load failed; using defaults. {err}")
        return {
            "newsapi_query_groups": list(NEWSAPI_QUERY_GROUPS),
            "google_rss_queries": list(GOOGLE_RSS_QUERIES),
            "newsapi_page_size": NEWSAPI_PAGE_SIZE,
            "newsapi_max_pages": NEWSAPI_MAX_PAGES,
            "google_items_per_query": GOOGLE_ITEMS_PER_QUERY,
            "path": "built-in-defaults",
            "fallback": True,
        }


def fetch_newsapi_forex(
    query_groups: list[str] | None = None,
    page_size: int = NEWSAPI_PAGE_SIZE,
    max_pages: int = NEWSAPI_MAX_PAGES,
) -> list[dict]:
    if not NEWS_API_KEY:
        return []

    groups = query_groups or list(NEWSAPI_QUERY_GROUPS)
    articles: list[dict] = []
    for query in groups:
        for page in range(1, max_pages + 1):
            params = {
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": page_size,
                "page": page,
                "apiKey": NEWS_API_KEY,
            }
            try:
                response = requests.get(NEWSAPI_ENDPOINT, params=params, timeout=12)
                response.raise_for_status()
                data = response.json()
            except requests.RequestException:
                log("NewsAPI fetch error: request failed.")
                break
            except Exception:
                log("NewsAPI fetch error: unexpected failure.")
                break

            raw_items = data.get("articles", [])
            if not isinstance(raw_items, list):
                break

            for item in raw_items:
                title = _clean_text(item.get("title", ""))
                if not title:
                    continue
                articles.append(
                    {
                        "source": "NewsAPI",
                        "title": title,
                        "description": _clean_text(item.get("description", "")),
                        "url": item.get("url") or "",
                        "published_at": item.get("publishedAt") or "",
                    }
                )

            if len(raw_items) < page_size:
                break

    return articles


def fetch_google_news_forex(
    queries: list[str] | None = None,
    items_per_query: int = GOOGLE_ITEMS_PER_QUERY,
) -> list[dict]:
    query_list = queries or list(GOOGLE_RSS_QUERIES)
    articles: list[dict] = []
    for query in query_list:
        feed_url = GOOGLE_RSS_TEMPLATE.format(query=quote_plus(query))
        try:
            feed = feedparser.parse(feed_url)
        except Exception:
            log("Google News RSS fetch error.")
            continue

        entries = getattr(feed, "entries", [])[:items_per_query]
        for entry in entries:
            title = _clean_text(entry.get("title", ""))
            if not title:
                continue
            articles.append(
                {
                    "source": "GoogleNews",
                    "title": title,
                    "description": _clean_text(entry.get("summary", "")),
                    "url": entry.get("link") or "",
                    "published_at": entry.get("published", ""),
                }
            )
    return articles


def fetch_forex_news() -> list[dict]:
    query_conf = _resolve_query_config()
    newsapi_articles = fetch_newsapi_forex(
        query_groups=list(query_conf["newsapi_query_groups"]),
        page_size=int(query_conf["newsapi_page_size"]),
        max_pages=int(query_conf["newsapi_max_pages"]),
    )
    google_news_articles = fetch_google_news_forex(
        queries=list(query_conf["google_rss_queries"]),
        items_per_query=int(query_conf["google_items_per_query"]),
    )
    combined = newsapi_articles + google_news_articles
    deduped = _dedupe_articles(combined)

    source_counts = Counter(item.get("source", "Unknown") for item in deduped)
    dropped = len(combined) - len(deduped)
    log(
        "Fetched "
        f"{len(deduped)} total news articles (raw={len(combined)}, dropped_duplicates={dropped})."
    )
    log(
        "Source mix: "
        + ", ".join(f"{source}={count}" for source, count in sorted(source_counts.items()))
    )
    log(
        "Query config: "
        f"path={query_conf['path']}; "
        f"newsapi_groups={len(query_conf['newsapi_query_groups'])}; "
        f"google_groups={len(query_conf['google_rss_queries'])}; "
        f"fallback={query_conf['fallback']}"
    )
    return deduped
