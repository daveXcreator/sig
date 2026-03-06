import json
from pathlib import Path
import unittest
import uuid

from app.news_query_config import (
    NewsQueryConfigError,
    load_news_query_config,
    validate_news_query_config,
)


class NewsQueryConfigTests(unittest.TestCase):
    def test_load_default_news_query_config(self):
        config = load_news_query_config("config/news_query_packs.json")
        self.assertGreaterEqual(len(config.newsapi_query_groups), 2)
        self.assertGreaterEqual(len(config.google_rss_queries), 2)
        self.assertGreater(config.newsapi_page_size, 0)

    def test_validate_news_query_config_rejects_missing_sections(self):
        bad = {"newsapi_query_groups": ["forex"]}
        with self.assertRaises(NewsQueryConfigError):
            validate_news_query_config(bad)

    def test_load_news_query_config_rejects_out_of_range_page_size(self):
        base_path = Path("config/news_query_packs.json")
        payload = json.loads(base_path.read_text(encoding="utf-8"))
        payload["newsapi_page_size"] = 0

        temp_dir = Path("artifacts") / f"test_news_query_config_{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            tmp_path = temp_dir / "queries.json"
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(NewsQueryConfigError):
                load_news_query_config(str(tmp_path))
        finally:
            for child in temp_dir.glob("*"):
                child.unlink(missing_ok=True)
            temp_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
