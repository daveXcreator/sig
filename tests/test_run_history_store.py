import unittest
from unittest.mock import Mock, patch

from app import run_history_store


class RunHistoryStoreTests(unittest.TestCase):
    @patch("app.run_history_store.RUN_HISTORY_REMOTE_BACKEND", "supabase")
    @patch("app.run_history_store.SUPABASE_URL", "https://example.supabase.co")
    @patch("app.run_history_store.SUPABASE_SERVICE_ROLE_KEY", "secret")
    @patch("app.run_history_store.RUN_HISTORY_SUPABASE_TABLE", "signalyze_run_history")
    @patch("app.run_history_store.requests.post")
    def test_append_run_history_posts_to_supabase(self, post_mock):
        response = Mock()
        response.raise_for_status.return_value = None
        post_mock.return_value = response

        summary = {
            "run_id": "run_1",
            "finished_at": "2026-03-08T18:00:00Z",
            "status": "ok",
            "reason": None,
        }

        run_history_store.append_run_history(summary)

        self.assertEqual(1, post_mock.call_count)
        _, kwargs = post_mock.call_args
        self.assertIn("json", kwargs)
        self.assertEqual("run_1", kwargs["json"][0]["run_id"])
        self.assertEqual(summary, kwargs["json"][0]["summary"])

    @patch("app.run_history_store.RUN_HISTORY_REMOTE_BACKEND", "supabase")
    @patch("app.run_history_store.SUPABASE_URL", "https://example.supabase.co")
    @patch("app.run_history_store.SUPABASE_SERVICE_ROLE_KEY", "secret")
    @patch("app.run_history_store.RUN_HISTORY_SUPABASE_TABLE", "signalyze_run_history")
    @patch("app.run_history_store.requests.get")
    def test_load_recent_run_history_reads_supabase_summaries(self, get_mock):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {
                "summary": {
                    "run_id": "run_2",
                    "finished_at": "2026-03-08T18:10:00Z",
                    "status": "ok",
                }
            }
        ]
        get_mock.return_value = response

        rows = run_history_store.load_recent_run_history(limit=5)

        self.assertEqual(1, len(rows))
        self.assertEqual("run_2", rows[0]["run_id"])
        self.assertEqual(1, get_mock.call_count)


if __name__ == "__main__":
    unittest.main()
