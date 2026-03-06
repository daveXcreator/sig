import tweepy

from app.config import (
    TWITTER_ACCESS_SECRET,
    TWITTER_ACCESS_TOKEN,
    TWITTER_API_KEY,
    TWITTER_API_SECRET,
)
from app.utils import log


def get_twitter_client() -> tweepy.API | None:
    credentials = [
        TWITTER_API_KEY,
        TWITTER_API_SECRET,
        TWITTER_ACCESS_TOKEN,
        TWITTER_ACCESS_SECRET,
    ]
    if not all(credentials):
        log("Twitter credentials are missing; skipping posts.")
        return None

    auth = tweepy.OAuth1UserHandler(
        TWITTER_API_KEY,
        TWITTER_API_SECRET,
        TWITTER_ACCESS_TOKEN,
        TWITTER_ACCESS_SECRET,
    )
    return tweepy.API(auth)


def send_tweet(text: str) -> bool:
    try:
        api = get_twitter_client()
        if api is None:
            return False
        api.update_status(status=text)
        log("Tweet posted successfully.")
        return True
    except Exception:
        log("Failed to tweet.")
        return False


def send_signals_to_twitter(signals: list) -> None:
    if not signals:
        return

    for signal in signals:
        tweet = (
            f"#{signal['pair'].replace('/', '')} Signal\n"
            f"{signal['signal'].upper()} - Confidence: {signal['confidence']:.2f}\n"
            f"RSI: {signal['rsi']:.2f}\n"
            "via Signalyze AI"
        )
        send_tweet(tweet)
