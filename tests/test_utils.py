import io
import json
import unittest
from unittest.mock import patch

from app.utils import generate_run_id, log_event


class UtilsTests(unittest.TestCase):
    def test_generate_run_id_has_prefix_and_entropy(self):
        run_id_a = generate_run_id("livev2")
        run_id_b = generate_run_id("livev2")

        self.assertTrue(run_id_a.startswith("livev2_"))
        self.assertTrue(run_id_b.startswith("livev2_"))
        self.assertNotEqual(run_id_a, run_id_b)

    def test_log_event_emits_json_with_expected_fields(self):
        stream = io.StringIO()
        with patch("sys.stdout", stream):
            log_event(
                stage="decision",
                event="signal_decision",
                run_id="run_test",
                signal_id="sig_123",
                latency_ms=12.345,
                result="publish",
                pair="EUR/USD",
            )

        payload = json.loads(stream.getvalue().strip())
        self.assertEqual("decision", payload["stage"])
        self.assertEqual("signal_decision", payload["event"])
        self.assertEqual("run_test", payload["run_id"])
        self.assertEqual("sig_123", payload["signal_id"])
        self.assertEqual("publish", payload["result"])
        self.assertEqual("EUR/USD", payload["pair"])
        self.assertEqual(12.35, payload["latency_ms"])
        self.assertIn("ts", payload)


if __name__ == "__main__":
    unittest.main()
