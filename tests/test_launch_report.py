from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import unittest
import uuid

from app.launch_report import build_production_day_report


class LaunchReportTests(unittest.TestCase):
    def test_build_production_day_report_filters_by_day(self):
        out_dir = Path("artifacts") / f"test_launch_report_{uuid.uuid4().hex}"
        out_dir.mkdir(parents=True, exist_ok=True)
        history_path = out_dir / "run_history.jsonl"

        today = datetime.now(timezone.utc).date().isoformat()
        payload_today = {
            "finished_at": f"{today}T01:00:00Z",
            "status": "ok",
            "articles": 40,
            "decisions": 4,
            "publish_candidate_signals": 2,
            "publish_stats": {"telegram": 1, "results": 0},
            "publishing_enabled": True,
            "calendar_events": 2,
        }
        payload_today_2 = {
            "finished_at": f"{today}T03:30:00Z",
            "status": "failed",
            "reason": "no_context",
            "articles": 10,
            "decisions": 0,
            "publish_candidate_signals": 0,
            "publish_stats": {"telegram": 0, "results": 0},
            "publishing_enabled": False,
            "calendar_events": 0,
        }
        payload_other_day = {
            "finished_at": "2026-01-01T01:00:00Z",
            "status": "ok",
            "articles": 99,
            "decisions": 9,
            "publish_candidate_signals": 5,
            "publish_stats": {"telegram": 5, "results": 1},
            "publishing_enabled": True,
            "calendar_events": 3,
        }
        history_path.write_text(
            "\n".join(
                [
                    json.dumps(payload_today),
                    json.dumps(payload_today_2),
                    json.dumps(payload_other_day),
                ]
            ),
            encoding="utf-8",
        )

        try:
            report = build_production_day_report(
                day_utc=today,
                history_path=history_path,
                output_dir=str(out_dir / "reports"),
            )
            summary = report["summary"]
            self.assertEqual(2, summary["runs"])
            self.assertEqual(1, summary["ok_runs"])
            self.assertEqual(1, summary["failed_runs"])
            self.assertEqual(50, summary["articles_total"])
            self.assertEqual(4, summary["decisions_total"])
            self.assertEqual(1, summary["signals_published"])
            self.assertTrue(Path(report["report_json"]).exists())
            self.assertTrue(Path(report["report_markdown"]).exists())
            self.assertTrue(report["next_tuning_actions"])
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
