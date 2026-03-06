import unittest
from unittest.mock import patch

from app.news_query_config import NewsQueryConfigError
from app.news_fetcher import NEWSAPI_QUERY_GROUPS, fetch_forex_news


class NewsFetcherTests(unittest.TestCase):
    @patch("app.news_fetcher.fetch_google_news_forex")
    @patch("app.news_fetcher.fetch_newsapi_forex")
    def test_fetch_forex_news_merges_and_deduplicates(self, newsapi_mock, google_mock):
        newsapi_mock.return_value = [
            {"title": "Dollar rises", "description": "", "source": "NewsAPI", "url": "", "published_at": ""}
        ]
        google_mock.return_value = [
            {"title": "Dollar rises", "description": "", "source": "GoogleNews", "url": "", "published_at": ""},
            {"title": "Yen weakens", "description": "", "source": "GoogleNews", "url": "", "published_at": ""},
        ]

        result = fetch_forex_news()

        self.assertEqual(2, len(result))
        self.assertEqual(["Dollar rises", "Yen weakens"], [item["title"] for item in result])

    @patch("app.news_fetcher.fetch_google_news_forex")
    @patch("app.news_fetcher.fetch_newsapi_forex")
    def test_fetch_forex_news_dedupes_near_duplicates_by_title_and_url(
        self,
        newsapi_mock,
        google_mock,
    ):
        newsapi_mock.return_value = [
            {
                "title": "Fed signals hawkish pause - Reuters",
                "description": "Dollar gains on policy path.",
                "source": "NewsAPI",
                "url": "https://example.com/story/fed?utm=abc",
                "published_at": "",
            }
        ]
        google_mock.return_value = [
            {
                "title": "Fed signals hawkish pause",
                "description": "Dollar gains on policy path.",
                "source": "GoogleNews",
                "url": "https://example.com/story/fed?ref=google",
                "published_at": "",
            }
        ]

        result = fetch_forex_news()

        self.assertEqual(1, len(result))
        self.assertEqual("Fed signals hawkish pause - Reuters", result[0]["title"])

    @patch("app.news_fetcher.fetch_google_news_forex")
    @patch("app.news_fetcher.fetch_newsapi_forex")
    @patch("app.news_fetcher.load_news_query_config")
    def test_fetch_forex_news_falls_back_to_defaults_when_query_config_fails(
        self,
        load_config_mock,
        newsapi_mock,
        google_mock,
    ):
        load_config_mock.side_effect = NewsQueryConfigError("bad config")
        newsapi_mock.return_value = []
        google_mock.return_value = []

        result = fetch_forex_news()

        self.assertEqual([], result)
        self.assertTrue(newsapi_mock.called)
        called_query_groups = newsapi_mock.call_args.kwargs.get("query_groups", [])
        self.assertEqual(list(NEWSAPI_QUERY_GROUPS), called_query_groups)


if __name__ == "__main__":
    unittest.main()
