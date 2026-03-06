from __future__ import annotations

import argparse

from app.confidence_calibration import run_calibration_job
from app.utils import log


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run confidence calibration scaffold job.",
    )
    parser.add_argument(
        "--outcomes-path",
        default="artifacts/live/outcomes.jsonl",
        help="Path to outcomes file (JSON or JSONL).",
    )
    parser.add_argument(
        "--model-path",
        default=None,
        help="Optional output path for the generated calibration model JSON.",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=100,
        help="Minimum outcomes required before falling back to mock outcomes.",
    )
    parser.add_argument(
        "--no-mock-fallback",
        action="store_true",
        help="Fail when outcomes are insufficient instead of using mock data.",
    )
    args = parser.parse_args()

    summary = run_calibration_job(
        outcomes_path=args.outcomes_path,
        model_path=args.model_path,
        min_samples=args.min_samples,
        use_mock_if_needed=not args.no_mock_fallback,
    )
    log(f"Calibration job summary: {summary}")


if __name__ == "__main__":
    main()
