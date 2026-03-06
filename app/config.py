import os
from dotenv import load_dotenv

load_dotenv()


def _get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is None:
        return None
    return value.strip()


def _get_bool_env(name: str, default: bool = False) -> bool:
    raw = _get_env(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


TELEGRAM_TOKEN = _get_env("TELEGRAM_TOKEN")
ALPHA_VANTAGE_KEY = _get_env("ALPHA_VANTAGE_KEY")
HF_API_TOKEN = _get_env("HF_API_TOKEN")
TELEGRAM_CHAT_ID = _get_env("TELEGRAM_CHAT_ID")
NEWS_API_KEY = _get_env("NEWS_API_KEY")
OPENAI_API_KEY = _get_env("OPENAI_API_KEY")
OPENAI_MODEL = _get_env("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini"
FMP_API_KEY = _get_env("FMP_API_KEY")
ENABLE_ECONOMIC_CALENDAR = _get_bool_env("ENABLE_ECONOMIC_CALENDAR", True)
ENABLE_CONFIDENCE_CALIBRATION = _get_bool_env("ENABLE_CONFIDENCE_CALIBRATION", True)
STRATEGY_CONFIG_PATH = _get_env("STRATEGY_CONFIG_PATH", "config/major_event_strategy.json") or "config/major_event_strategy.json"
NEWS_QUERY_CONFIG_PATH = _get_env("NEWS_QUERY_CONFIG_PATH", "config/news_query_packs.json") or "config/news_query_packs.json"
CALIBRATION_MODEL_PATH = _get_env("CALIBRATION_MODEL_PATH", "artifacts/live/calibration_model.json") or "artifacts/live/calibration_model.json"
RUN_HISTORY_PATH = _get_env("RUN_HISTORY_PATH", "artifacts/live/run_history.jsonl") or "artifacts/live/run_history.jsonl"
ENABLE_PUBLIC_POSTING = _get_bool_env("ENABLE_PUBLIC_POSTING", True)
ROLLBACK_SWITCH_FILE = _get_env("ROLLBACK_SWITCH_FILE", "artifacts/live/ROLLBACK") or "artifacts/live/ROLLBACK"
TWITTER_API_KEY = _get_env("TWITTER_API_KEY")
TWITTER_API_SECRET = _get_env("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = _get_env("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = _get_env("TWITTER_ACCESS_SECRET")
PEXELS_API_KEY = _get_env("PEXELS_API_KEY")
TELEGRAM_IMAGE_MODE = (_get_env("TELEGRAM_IMAGE_MODE", "auto") or "auto").lower()
ENABLE_TELEGRAM_IMAGES = _get_bool_env("ENABLE_TELEGRAM_IMAGES", False)
ENABLE_CHART_IMAGES = _get_bool_env("ENABLE_CHART_IMAGES", True)
MAX_PUBLISHABLE_SIGNALS_PER_RUN = int(os.getenv("MAX_PUBLISHABLE_SIGNALS_PER_RUN", 3))
TRADE_STATE_PATH = _get_env("TRADE_STATE_PATH", "artifacts/live/trade_state.json") or "artifacts/live/trade_state.json"
OPERATOR_API_KEY = _get_env("OPERATOR_API_KEY")
ENABLE_BACKGROUND_LOOP = _get_bool_env("ENABLE_BACKGROUND_LOOP", True)
MAX_EXTRACTION_ARTICLES = int(os.getenv("MAX_EXTRACTION_ARTICLES", 20))
REQUIRE_MAJOR_EVENT_FILTER = _get_bool_env("REQUIRE_MAJOR_EVENT_FILTER", True)

FETCH_INTERVAL_MINUTES = int(os.getenv("FETCH_INTERVAL_MINUTES", 15))
BACKGROUND_LOOP_INTERVAL_MINUTES = int(
    os.getenv("BACKGROUND_LOOP_INTERVAL_MINUTES", FETCH_INTERVAL_MINUTES)
)
RSI_PERIOD = int(os.getenv("RSI_PERIOD", 14))
RSI_THRESHOLD_OVERSOLD = int(os.getenv("RSI_THRESHOLD_OVERSOLD", 30))
RSI_THRESHOLD_OVERBOUGHT = int(os.getenv("RSI_THRESHOLD_OVERBOUGHT", 70))
