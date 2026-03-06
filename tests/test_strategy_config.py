import json
from pathlib import Path
import unittest
import uuid

from app.strategy_config import (
    StrategyConfigError,
    load_major_event_strategy,
    validate_major_event_strategy,
)


class StrategyConfigTests(unittest.TestCase):
    def test_load_default_major_event_strategy(self):
        config = load_major_event_strategy("config/major_event_strategy.json")
        self.assertEqual("major_event_strategy", config.metadata["name"])
        self.assertIn("rate_decision", config.event_universe["primary"])
        self.assertGreater(config.pair_multipliers["USD/JPY"], 1.0)

    def test_validate_major_event_strategy_rejects_missing_sections(self):
        bad = {"metadata": {"name": "x"}}
        with self.assertRaises(StrategyConfigError):
            validate_major_event_strategy(bad)

    def test_load_major_event_strategy_rejects_invalid_loss_threshold(self):
        base_path = Path("config/major_event_strategy.json")
        payload = json.loads(base_path.read_text(encoding="utf-8"))
        payload["lifecycle"]["loss_r_multiple_threshold"] = 0.1

        temp_dir = Path("artifacts") / f"test_strategy_config_{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            tmp_path = temp_dir / "strategy.json"
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(StrategyConfigError):
                load_major_event_strategy(str(tmp_path))
        finally:
            for child in temp_dir.glob("*"):
                child.unlink(missing_ok=True)
            temp_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
