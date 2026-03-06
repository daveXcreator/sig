from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from app.confidence_calibration import (
    load_calibration_model,
    load_outcome_points,
    run_calibration_job,
)
from app.signal_engine import calibrate_confidence


class _ModelStub:
    def __init__(self, value: float):
        self.value = value

    def apply(self, confidence_raw: float) -> float:
        _ = confidence_raw
        return self.value


class ConfidenceCalibrationTests(unittest.TestCase):
    def test_run_calibration_job_with_mock_fallback_writes_model(self):
        out_dir = Path("artifacts") / f"test_calibration_{uuid.uuid4().hex}"
        model_path = out_dir / "calibration_model.json"
        missing_outcomes = out_dir / "missing.jsonl"
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            summary = run_calibration_job(
                outcomes_path=missing_outcomes,
                model_path=model_path,
                min_samples=80,
                use_mock_if_needed=True,
            )
            self.assertEqual("ok", summary["status"])
            self.assertEqual("mock_outcomes", summary["source"])
            self.assertTrue(model_path.exists())

            model = load_calibration_model(model_path)
            self.assertIsNotNone(model)
            assert model is not None
            self.assertGreaterEqual(model.fitted_samples, 80)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

    def test_load_outcome_points_from_jsonl(self):
        out_dir = Path("artifacts") / f"test_outcomes_{uuid.uuid4().hex}"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "outcomes.jsonl"
        path.write_text(
            "\n".join(
                [
                    '{"confidence_raw": 0.7, "directional_success": true}',
                    '{"confidence": 0.4, "success": false}',
                    '{"bad": "row"}',
                ]
            ),
            encoding="utf-8",
        )

        try:
            points = load_outcome_points(path)
            self.assertEqual([(0.7, 1), (0.4, 0)], points)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

    def test_signal_engine_uses_active_model_when_available(self):
        with patch("app.signal_engine.get_active_calibration_model", return_value=_ModelStub(0.33)):
            calibrated = calibrate_confidence(0.88)
        self.assertAlmostEqual(0.33, calibrated, places=6)


if __name__ == "__main__":
    unittest.main()
