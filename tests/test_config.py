import importlib
import os
import unittest

import app.config


class ConfigTests(unittest.TestCase):
    def test_openai_model_has_default(self):
        self.assertIsInstance(app.config.OPENAI_MODEL, str)
        self.assertTrue(app.config.OPENAI_MODEL)

    def test_rsi_values_are_integers(self):
        self.assertIsInstance(app.config.RSI_PERIOD, int)
        self.assertIsInstance(app.config.RSI_THRESHOLD_OVERSOLD, int)
        self.assertIsInstance(app.config.RSI_THRESHOLD_OVERBOUGHT, int)
        self.assertIsInstance(app.config.STRATEGY_CONFIG_PATH, str)
        self.assertTrue(app.config.STRATEGY_CONFIG_PATH)

    def test_model_default_when_env_not_set(self):
        original = os.environ.pop("OPENAI_MODEL", None)
        importlib.reload(app.config)
        try:
            self.assertEqual("gpt-4o-mini", app.config.OPENAI_MODEL)
        finally:
            if original is not None:
                os.environ["OPENAI_MODEL"] = original
            importlib.reload(app.config)


if __name__ == "__main__":
    unittest.main()
