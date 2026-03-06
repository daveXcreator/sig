from pathlib import Path
import shutil
import unittest
import uuid

from app.shadow_run import run_shadow_session


class ShadowRunTests(unittest.TestCase):
    def test_run_shadow_session_generates_report(self):
        out_dir = Path("artifacts") / f"test_shadow_{uuid.uuid4().hex}"
        out_dir.mkdir(parents=True, exist_ok=True)

        calls = {"count": 0}

        def runner(**kwargs):
            _ = kwargs
            calls["count"] += 1
            return {
                "status": "ok",
                "articles": 10,
                "impacts": 4,
                "contexts": 4,
                "decisions": 3,
                "publish_candidate_signals": 2,
                "policy_published": 1,
                "policy_failed_hard_gate": 1,
                "policy_failed_thresholds": 1,
            }

        try:
            report = run_shadow_session(
                iterations=2,
                interval_seconds=0.0,
                output_dir=str(out_dir),
                runner=runner,
                sleep_fn=lambda _: None,
            )

            self.assertEqual(2, calls["count"])
            self.assertEqual("shadow_run", report["mode"])
            self.assertEqual(2, report["runs_executed"])
            self.assertEqual(2, report["successful_runs"])
            self.assertIn("policy_failed_hard_gate", report["rejection_causes"])
            self.assertTrue(Path(report["report_json"]).exists())
            self.assertTrue(Path(report["report_markdown"]).exists())
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
