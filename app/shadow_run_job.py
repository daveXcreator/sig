from __future__ import annotations

import argparse

from app.shadow_run import run_shadow_session
from app.utils import log


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Signalyze AI shadow mode session.")
    parser.add_argument(
        "--iterations",
        type=int,
        default=96,
        help="How many pipeline cycles to run in shadow mode.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=900.0,
        help="Delay between cycles in seconds.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/shadow_run",
        help="Directory where the shadow report will be written.",
    )
    args = parser.parse_args()

    summary = run_shadow_session(
        iterations=args.iterations,
        interval_seconds=args.interval_seconds,
        output_dir=args.output_dir,
    )
    log(f"Shadow run summary: {summary}")


if __name__ == "__main__":
    main()
