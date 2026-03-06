import argparse
from typing import Any

from app.confidence_calibration import run_calibration_job
from app.dry_run_pipeline import run_dry_pipeline
from app.launch_report import build_production_day_report
from app.shadow_run import run_shadow_session
from app.unified_pipeline import run_live_v2
from app.utils import log

ALLOWED_SENTIMENTS = {"bullish", "bearish", "neutral"}


def aggregate_sentiment_by_pair(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_pair: dict[str, dict[str, Any]] = {}

    for item in records:
        pair = item.get("pair")
        sentiment = item.get("sentiment")
        confidence = item.get("confidence", 0)

        if not pair or sentiment not in ALLOWED_SENTIMENTS:
            continue

        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0

        normalized = {
            "pair": pair,
            "sentiment": sentiment,
            "confidence": max(0.0, min(confidence, 1.0)),
        }
        existing = best_by_pair.get(pair)
        if existing is None or normalized["confidence"] > existing["confidence"]:
            best_by_pair[pair] = normalized

    return list(best_by_pair.values())


def run() -> None:
    log("Signalyze AI live V2 started")
    run_live_v2(enable_x=False)
    log("Signalyze AI live V2 finished")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Signalyze AI")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run end-to-end dry pipeline and write artifact outputs locally.",
    )
    parser.add_argument(
        "--dry-run-output",
        default="artifacts/dry_run",
        help="Output directory for dry-run artifacts.",
    )
    parser.add_argument(
        "--shadow-run",
        action="store_true",
        help="Run repeated live pipeline cycles in shadow mode (no public posting).",
    )
    parser.add_argument(
        "--shadow-iterations",
        type=int,
        default=96,
        help="Number of cycles for shadow mode.",
    )
    parser.add_argument(
        "--shadow-interval-seconds",
        type=float,
        default=900.0,
        help="Seconds between shadow-mode cycles.",
    )
    parser.add_argument(
        "--shadow-output",
        default="artifacts/shadow_run",
        help="Output directory for shadow reports.",
    )
    parser.add_argument(
        "--run-calibration-job",
        action="store_true",
        help="Run calibration scaffold and write calibration model.",
    )
    parser.add_argument(
        "--calibration-outcomes-path",
        default="artifacts/live/outcomes.jsonl",
        help="Outcomes input path for calibration job.",
    )
    parser.add_argument(
        "--calibration-min-samples",
        type=int,
        default=100,
        help="Minimum real outcomes before mock fallback.",
    )
    parser.add_argument(
        "--no-calibration-mock-fallback",
        action="store_true",
        help="Disable mock fallback when calibration outcomes are insufficient.",
    )
    parser.add_argument(
        "--build-production-report",
        action="store_true",
        help="Build production-day report from run history.",
    )
    parser.add_argument(
        "--report-day-utc",
        default=None,
        help="UTC date for production report (YYYY-MM-DD).",
    )
    args = parser.parse_args()

    if args.dry_run:
        run_dry_pipeline(output_dir=args.dry_run_output)
    elif args.shadow_run:
        run_shadow_session(
            iterations=args.shadow_iterations,
            interval_seconds=args.shadow_interval_seconds,
            output_dir=args.shadow_output,
        )
    elif args.run_calibration_job:
        run_calibration_job(
            outcomes_path=args.calibration_outcomes_path,
            min_samples=args.calibration_min_samples,
            use_mock_if_needed=not args.no_calibration_mock_fallback,
        )
    elif args.build_production_report:
        build_production_day_report(day_utc=args.report_day_utc)
    else:
        run()
