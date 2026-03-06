import json
from pathlib import Path
import shutil
import unittest
import uuid

from app.dry_run_pipeline import run_dry_pipeline


class DryRunPipelineTests(unittest.TestCase):
    def test_dry_run_writes_artifacts_and_summary(self):
        raw_articles = [
            {
                "source": "TestWire",
                "title": "ECB hawkish tilt lifts euro against dollar",
                "description": "European Central Bank comments push EUR higher.",
                "url": "https://example.com/a1",
                "published_at": "2026-02-28T00:00:00Z",
            },
            {
                "source": "TestWire",
                "title": "BOJ dovish message weakens yen",
                "description": "Bank of Japan policy stance keeps pressure on JPY.",
                "url": "https://example.com/a2",
                "published_at": "2026-02-28T00:10:00Z",
            },
        ]

        out = Path("artifacts") / f"test_dry_run_{uuid.uuid4().hex}"
        out.mkdir(parents=True, exist_ok=True)
        try:
            summary = run_dry_pipeline(raw_articles=raw_articles, output_dir=str(out))
            out = Path(summary["output_dir"])

            expected_files = [
                "normalized_articles.json",
                "pair_impacts.json",
                "market_context.json",
                "decisions.json",
                "simulated_posts.json",
                "summary.json",
            ]
            for filename in expected_files:
                self.assertTrue((out / filename).exists(), f"{filename} should exist")

            summary_payload = json.loads((out / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual("dry_run", summary_payload["run_mode"])
            self.assertEqual(2, summary_payload["input_articles"])
            self.assertGreaterEqual(summary_payload["normalized_articles"], 2)

            decisions = json.loads((out / "decisions.json").read_text(encoding="utf-8"))
            self.assertTrue(decisions)
            for item in decisions:
                self.assertIn(item["decision"], {"publish", "hold", "reject"})

            posts = json.loads((out / "simulated_posts.json").read_text(encoding="utf-8"))
            self.assertIn("telegram_preview", posts)
            self.assertIsInstance(posts["telegram_preview"], str)
            self.assertIn("Signalyze AI Free Signals", posts["telegram_preview"])
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
