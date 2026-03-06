import requests
import time

from app.config import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN
from app.utils import log

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.0
TELEGRAM_CAPTION_MAX_CHARS = 1024


def _has_credentials() -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram credentials are missing; skipping send.")
        return False
    return True


def send_telegram_message(text: str, parse_mode: str = "Markdown") -> bool:
    if not _has_credentials():
        return False

    telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                telegram_api_url,
                json=payload,
                timeout=10,
                headers={"User-Agent": "signalyze-ai/1.0"},
            )
            response.raise_for_status()
            log("Telegram message sent.")
            return True
        except requests.HTTPError as err:
            status = err.response.status_code if err.response is not None else 0
            if status == 400 and payload.get("parse_mode"):
                payload.pop("parse_mode", None)
                continue
            if attempt == MAX_RETRIES:
                detail = ""
                if err.response is not None:
                    try:
                        detail = (err.response.text or "").strip()
                    except Exception:
                        detail = ""
                if detail:
                    log(f"Telegram send failed: HTTP {status}. {detail}")
                else:
                    log("Telegram send failed: HTTP error.")
                return False
        except requests.RequestException:
            if attempt == MAX_RETRIES:
                log("Telegram send failed: request failed.")
                return False
        except Exception:
            log("Telegram send failed: unexpected failure.")
            return False

        time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    return False


def send_telegram_photo(
    photo_url: str,
    caption: str = "",
    parse_mode: str = "Markdown",
) -> bool:
    if not _has_credentials():
        return False
    if not photo_url:
        return False

    safe_caption = str(caption or "")
    if len(safe_caption) > TELEGRAM_CAPTION_MAX_CHARS:
        safe_caption = safe_caption[: TELEGRAM_CAPTION_MAX_CHARS - 3].rstrip() + "..."

    telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": photo_url,
        "caption": safe_caption,
        "parse_mode": parse_mode,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                telegram_api_url,
                json=payload,
                timeout=15,
                headers={"User-Agent": "signalyze-ai/1.0"},
            )
            response.raise_for_status()
            log("Telegram photo sent.")
            return True
        except requests.HTTPError as err:
            status = err.response.status_code if err.response is not None else 0
            if status == 400 and payload.get("parse_mode"):
                payload.pop("parse_mode", None)
                continue
            if attempt == MAX_RETRIES:
                detail = ""
                if err.response is not None:
                    try:
                        detail = (err.response.text or "").strip()
                    except Exception:
                        detail = ""
                if detail:
                    log(f"Telegram photo send failed: HTTP {status}. {detail}")
                else:
                    log("Telegram photo send failed: HTTP error.")
                return False
        except requests.RequestException:
            if attempt == MAX_RETRIES:
                log("Telegram photo send failed: request failed.")
                return False
        except Exception:
            log("Telegram photo send failed: unexpected failure.")
            return False

        time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    return False


def send_signals(signals: list) -> None:
    if not signals:
        log("No signals to send.")
        return

    header = "Signalyze AI Forex Signals\n"
    body = "\n".join(s["message"] for s in signals)
    footer = "\nSignals are AI-assisted with RSI confirmation."

    full_message = header + "\n" + body + footer
    send_telegram_message(full_message)
