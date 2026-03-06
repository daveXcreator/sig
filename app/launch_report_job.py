from __future__ import annotations

import argparse

from app.launch_report import build_production_day_report
from app.utils import log


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Signalyze production-day report.")
    parser.add_argument(
        "--day-utc",
        default=None,
        help="Target day in YYYY-MM-DD UTC format. Defaults to today UTC.",
    )
    parser.add_argument(
        "--history-path",
        default=None,
        help="Optional run history JSONL path. Defaults to configured RUN_HISTORY_PATH.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/live/reports",
        help="Output directory for report files.",
    )
    args = parser.parse_args()

    kwargs = {
        "day_utc": args.day_utc,
        "output_dir": args.output_dir,
    }
    if args.history_path:
        kwargs["history_path"] = args.history_path

    report = build_production_day_report(**kwargs)
    log(f"Production day report summary: {report}")


if __name__ == "__main__":
    main()
